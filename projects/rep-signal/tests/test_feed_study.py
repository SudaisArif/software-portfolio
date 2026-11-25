"""The fast cut keeps exact spoken wording and measured caption boundaries."""
import copy
import importlib.util
import unittest


HAS_DEPS=all(importlib.util.find_spec(module) for module in ('PIL','numpy'))


@unittest.skipUnless(HAS_DEPS,'Renderer dependencies required')
class FeedStudyTests(unittest.TestCase):
    def segment(self):
        text='But if your reps keep falling off a cliff, try resting longer and compare.'
        words=[{'text':word,'start':i*.3,'end':i*.3+.25} for i,word in enumerate(text.split())]
        return {'id':'f01','text':text,'start':0,'end':4.15,'words':words}

    def test_semantic_phrases_preserve_words_and_actual_times(self):
        from renderer.feed_study import short_captions
        segment=self.segment();phrases=['But if your reps','keep falling off a cliff,','try resting longer','and compare.']
        cues=short_captions([segment],{'segments':[{'id':'f01','caption_phrases':phrases}]})
        self.assertEqual([cue['text'] for cue in cues],phrases)
        self.assertEqual(' '.join(c['text'] for c in cues),segment['text'])
        self.assertEqual(cues[1]['start'],segment['words'][4]['start'])
        self.assertEqual(cues[1]['end'],segment['words'][8]['end'])
        self.assertTrue(all(2<=len(c['text'].split())<=5 for c in cues))

    def test_reworded_or_overlong_captions_are_rejected(self):
        from renderer.feed_study import short_captions
        segment=self.segment()
        for phrases in [['But if your gains','keep falling off a cliff,','try resting longer','and compare.'],[segment['text']]]:
            with self.subTest(phrases=phrases),self.assertRaises(ValueError):
                short_captions([segment],{'segments':[{'id':'f01','caption_phrases':phrases}]})

    def test_closing_hold_and_comparison_are_bounded(self):
        from renderer.feed_study import build_shots
        seg=[{'id':'f01','start':.1}]
        edit={'closing_hold_seconds':.65,'segments':[{'id':'f01','shots':[{'shot':'a','source_start':0,'right_shot':'b','right_source_start':0}]}]}
        beats,duration=build_shots(edit,seg,34.88)
        self.assertGreater(duration,34.88);self.assertLessEqual(duration,35.55)
        self.assertEqual(beats[0]['start'],0);self.assertEqual(beats[-1]['end'],duration)
        bad=copy.deepcopy(edit);bad['segments'][0]['shots'][0]['right_source_start']=float('nan')
        with self.assertRaisesRegex(ValueError,'comparison'):
            build_shots(bad,seg,34.88)
        bad=copy.deepcopy(edit);bad['closing_hold_seconds']=30
        with self.assertRaisesRegex(ValueError,'hold'):
            build_shots(bad,seg,34.88)


if __name__=='__main__':unittest.main()
