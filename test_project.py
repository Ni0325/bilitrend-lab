import json, unittest
from unittest.mock import patch
import requests
import numpy as np
import engine
import app as server

class ProjectTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.m=engine.Model();cls.d=json.loads((engine.ROOT/'data'/'bundle.json').read_text())
  server.model,server.payload=cls.m,cls.d;cls.c=server.app.test_client()
 def test_rows_and_features(self):
  self.assertEqual(sum(len(f['rows']) for f in self.d['snapshots']),13320)
  self.assertEqual(len(self.d['snapshots']),444)
  for t in self.m.all_tracks:
   hours=[p['hour'] for p in t['points']]
   self.assertTrue(all(b>a for a,b in zip(hours,hours[1:])))
   self.assertTrue(np.isfinite(engine.features(t)).all())
   for p in t['points']:
    self.assertIsNone(p['heat']);self.assertAlmostEqual(p['index'],(31-p['rank'])/30*100,places=2)
 def test_time_split_and_future_independence(self):
  cutoff=self.m.meta['cutoff']
  self.assertTrue(all(t['end']<cutoff for t in self.m.train))
  self.assertTrue(all(t['start']>cutoff for t in self.m.test))
  t=max(self.m.test,key=lambda t:len(t['points']));before=self.m.predict(t,3)
  edited=dict(t,points=t['points'][:3]+[{**p,'rank':1,'negative':100} for p in t['points'][3:]])
  self.assertEqual(before,self.m.predict(edited,3))
  for match in before['matches']:
   self.assertLess(self.m.by_id[match['reference']]['end'],cutoff)
   self.assertTrue(all(p['hour']<=t['points'][2]['hour'] for p in match['reference_points']))
 def test_synthetic_isolation_and_alerts(self):
  cases=engine.synthetic_cases()
  self.assertEqual([engine.warning(t['points'])['level'] for t in cases],['疑似争议升级','疑似反转振荡','观察不足'])
  self.assertFalse(set(t['id'] for t in cases)&set(self.m.by_id))
  self.assertEqual(engine.warning(cases[0]['points'][:1])['severity'],0)
  sparse=[dict(p) for p in cases[0]['points']];sparse[-1]['hour']=20
  self.assertEqual(engine.warning(sparse)['level'],'数据稀疏')
 def test_similarity(self):
  self.assertGreaterEqual(engine.title_similarity('某品牌新产品正式发布','某品牌新产品今日正式发布'),.84)
  self.assertEqual(engine.title_similarity('某品牌新产品正式发布','某品牌新产品未正式发布'),0)
  self.assertEqual(engine.title_similarity('战队甲战胜战队乙','战队甲不敌战队乙'),0)
 def test_api(self):
  self.assertEqual(self.c.get('/api/bundle').status_code,200)
  self.assertEqual(self.c.get('/api/topic/missing').status_code,404)
  self.assertEqual(self.c.get('/api/topic/'+self.m.test[0]['id']+'?count=0').status_code,400)
  sample=dict(captured_at='2026-11-02T14:00:00+08:00',topics=[dict(title='输入验证',rank=5,heat=None)])
  self.assertEqual(self.c.post('/api/validate',json=sample).status_code,200)
  sample['topics'][0]['rank']=-1
  self.assertEqual(self.c.post('/api/validate',json=sample).status_code,400)
  server.last_collect=-float('inf')
  with patch('app.collect',side_effect=requests.HTTPError('HTTP 412')):r=self.c.post('/api/collect')
  self.assertEqual(r.status_code,502);self.assertIn('未保存',r.json['error']);self.assertIsNone(r.json['snapshot'])
  self.assertEqual(self.c.post('/api/collect').status_code,429)
  self.assertFalse(self.c.post('/api/collector/stop').json['running'])

if __name__=='__main__':unittest.main(verbosity=2)
