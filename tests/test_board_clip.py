import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from board_clip import outline_contours, clip_mask, outside_regions, clipping_commands
from gerber_silkscreen_editor import GerberLayer
from PIL import Image


class BoardClipTests(unittest.TestCase):
    def test_reconstructs_unordered_and_reversed_edges_without_aperture_offset(self):
        layer = GerberLayer()
        layer.drawables = [dict(type='line', x1=a[0], y1=a[1], x2=b[0], y2=b[1], width=1)
                           for a, b in [((10, 5), (0, 5)), ((0, 0), (10, 0)),
                                        ((0, 5), (0, 0)), ((10, 5), (10, 0))]]
        paths = outline_contours(layer)
        self.assertEqual(len(paths), 1)
        self.assertEqual(set(paths[0]), {(0,0),(10,0),(10,5),(0,5)})
        layer.drawables.pop()
        with self.assertRaisesRegex(ValueError, 'cerrado'):
            outline_contours(layer)

    def test_hand_position_controls_crop_without_rescaling_or_recentering(self):
        board = [[(0,0),(10,0),(10,5),(0,5),(0,0)]]
        image = Image.new('L', (400,200), 255)
        first = clip_mask(image, board, 8,1,4,2)
        second = clip_mask(image, board, 9,1,4,2)
        self.assertEqual(first.getpixel((100,100)), 255)
        self.assertEqual(first.getpixel((300,100)), 0)
        self.assertEqual(second.getpixel((50,100)), 255)
        self.assertEqual(second.getpixel((150,100)), 0)
        self.assertEqual(image.getextrema(), (255,255))

    def test_concave_board_and_nested_cutout_match_export_regions(self):
        board = [[(0,0),(10,0),(10,4),(4,4),(4,10),(0,10),(0,0)],
                 [(1,1),(3,1),(3,3),(1,3),(1,1)]]
        original = Image.new('L', (1200,1200),255)
        kept = clip_mask(original, board, -1,-1,12,12)
        from PIL import ImageDraw
        cleared = original.copy()
        draw = ImageDraw.Draw(cleared)
        for path in outside_regions(board,(-1,-1,11,11)):
            draw.polygon([((x+1)*100,(11-y)*100) for x,y in path],fill=0)
        for x,y,expected in [(2,2,0),(2,5,255),(7,2,255),(7,7,0),(-.5,5,0)]:
            px,py=round((x+1)*100),round((11-y)*100)
            self.assertEqual(kept.getpixel((px,py)),expected)
            self.assertEqual(cleared.getpixel((px,py)),expected)

    def test_inch_export_clips_at_centerline_not_stroke_edge(self):
        layer = GerberLayer(); layer.unit='IN'; layer.format_x=layer.format_y=(2,4)
        commands = clipping_commands([[(0,0),(25.4,0),(25.4,25.4),(0,25.4),(0,0)]],
                                     (-1,-1,26.4,26.4),layer)
        self.assertIn('%LPC*%',commands)
        self.assertTrue(any('X10000Y' in c for c in commands))
        self.assertEqual(commands[-2:],['%LPD*%','G01*'])


if __name__ == '__main__': unittest.main()
