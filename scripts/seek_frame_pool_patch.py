#!/usr/bin/env python3
"""Test A/B: eliminate 2-frame MediaCodec wrapper starvation after runtime Seek.

RUN662 observed (epoch 3 after backward seek):
  engineLoops grew ~800/second, parser queued >1800 video packets;
  engine cNow/cNext were valid, but decodeFrame=0/engine decQ=0,
  decoder hwInput and renderSeq never advanced.
sfdec2 is configured with only TWO VIDEO_FRAME containers. At a seek boundary,
one can remain at the video sink and one in async codec receive; the engine
has no free frame to drive further decoding, so the pool cannot refill.
Increase wrappers to 4, retaining exact same hardware output memory ownership,
queue API, renderer, sync, and all buffering limits.
The strict 16-seek video-render regression must prove this change.
"""
import argparse
from pathlib import Path
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--native',type=Path,required=True)
    a=p.parse_args()
    file=a.native/'Source/codec_sfdec2.c'
    s=file.read_text()
    needle='static int sfdec_max_frames = 2;'
    assert s.count(needle)==1, 'sfdec2 wrapper pool anchor changed'
    assert 'NOVA_SEEK_FRAME_POOL_V1' not in s
    s=s.replace(needle,
        '/* NOVA_SEEK_FRAME_POOL_V1: avoid sink/decoder two-container deadlock '
        'after repeated seeks. */\n'
        'static int sfdec_max_frames = 4;',1)
    file.write_text(s)
    print('NOVA_SEEK_FRAME_POOL_V1=4 WRAPPERS')
if __name__ == '__main__':
    main()
