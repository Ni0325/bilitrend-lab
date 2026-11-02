"""仅绑定本机。历史分析与当前采集相互隔离。"""
import argparse
import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from flask import Flask, jsonify, request, send_from_directory
from engine import ROOT, Model, bundle, validate_snapshot
from collector import collect

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 2*1024*1024
model = None
payload = None
train_lock = threading.Lock()
collect_lock = threading.Lock()
state_lock = threading.Lock()
stop_event = threading.Event()
worker = None
last_collect = -float('inf')
state = dict(running=False, message='尚未尝试采集', last_attempt=None, snapshot=None)


def train():
    global model, payload
    fresh = Model()
    packed = bundle(fresh)
    model, payload = fresh, packed
    return packed


def status():
    with state_lock: return dict(state)


def attempt_collect():
    global last_collect
    if not collect_lock.acquire(blocking=False):
        return dict(error='已有采集请求正在进行'), 429
    try:
        if time.monotonic()-last_collect < 60:
            return dict(error='请至少间隔60秒再采集'), 429
        last_collect = time.monotonic()
        with state_lock:
            state.update(last_attempt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), message='正在请求B站')
        try:
            snapshot = collect()
            with state_lock: state.update(snapshot=snapshot, message='采集成功，保存至data/live；未混入历史数据。')
            return status(), 200
        except (requests.RequestException, ValueError, TypeError) as exc:
            with state_lock: state['message'] = '采集失败，未保存新快照：'+str(exc)
            return status() | dict(error=state['message']), 502
    finally: collect_lock.release()


def collector_loop():
    try:
        while not stop_event.is_set():
            attempt_collect()
            if stop_event.wait(1800): break
    finally:
        with state_lock: state['running'] = False


@app.get('/')
def index(): return send_from_directory(app.static_folder, 'index.html')


@app.get('/api/bundle')
def get_bundle():
    if payload is None: return jsonify(error='模型尚未就绪'), 503
    return jsonify(payload)


@app.get('/api/overview')
def overview():
    if model is None: return jsonify(error='模型尚未就绪'), 503
    return jsonify(model.overview())


@app.get('/api/topic/<topic_id>')
def topic(topic_id):
    current = model
    if current is None: return jsonify(error='模型尚未就绪'), 503
    track = current.by_id.get(topic_id)
    if not track: return jsonify(error='没有找到话题'), 404
    try:
        count = int(request.args.get('count', len(track['points'])))
        if not 1 <= count <= len(track['points']): raise ValueError()
    except ValueError: return jsonify(error='观测点数量超出范围'), 400
    return jsonify(observed=track['points'][:count], prediction=current.predict(track, count))


@app.post('/api/train')
def retrain():
    if not train_lock.acquire(blocking=False): return jsonify(error='训练正在进行'), 429
    try: return jsonify(train())
    except ValueError as exc: return jsonify(error=str(exc)), 400
    finally: train_lock.release()


@app.post('/api/collect')
def collect_now():
    result, code = attempt_collect()
    return jsonify(result), code


@app.get('/api/collector/status')
def collector_status(): return jsonify(status())


@app.post('/api/collector/start')
def start_collector():
    global worker
    with state_lock:
        if worker is not None and worker.is_alive():
            return jsonify(error='定时任务仍在运行或正在结束，请稍后再试'), 409
        stop_event.clear()
        state.update(running=True, message='定时采集已启动，关闭服务后停止')
        worker = threading.Thread(target=collector_loop, daemon=True)
        worker.start()
    return jsonify(status())


@app.post('/api/collector/stop')
def stop_collector():
    stop_event.set()
    with state_lock: state.update(running=False, message='已停止定时采集；正在进行的请求结束后退出')
    return jsonify(status())


@app.post('/api/validate')
def validate():
    try:
        snap = validate_snapshot(request.get_json(silent=True))
        return jsonify(valid=True, count=len(snap['topics']), message='字段校验通过；本操作不写入数据，单份快照不足以形成轨迹。')
    except (ValueError, TypeError, KeyError, AttributeError) as exc: return jsonify(error=str(exc)), 400


@app.get('/api/provenance')
def provenance(): return jsonify(json.loads((ROOT/'data'/'provenance.json').read_text()))


@app.errorhandler(413)
def too_large(exc): return jsonify(error='请求超过2MB限制'), 413


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    print('正在计算模型与历史回放数据…', flush=True)
    train()
    app.run(host='127.0.0.1', port=args.port, debug=False)
