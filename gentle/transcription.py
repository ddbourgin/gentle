import csv
import io
import json
import math
import logging
import wave

from multiprocessing.pool import ThreadPool as Pool

class MultiThreadedTranscriber:
    def __init__(self, kaldi_queue, chunk_len=20, overlap_t=2, nthreads=4):
        self.chunk_len = chunk_len
        self.overlap_t = overlap_t
        self.nthreads = nthreads
            
        self.kaldi_queue = kaldi_queue

    def transcribe(self, wavfile, progress_cb=None):
        wav_obj = wave.open(wavfile, 'r')
        duration = wav_obj.getnframes() / float(wav_obj.getframerate())
        n_chunks = int(math.ceil(duration / float(self.chunk_len - self.overlap_t)))

        chunks = []

        def transcribe_chunk(idx):
            wav_obj = wave.open(wavfile, 'r')
            start_t = idx * (self.chunk_len - self.overlap_t)
            # Seek
            wav_obj.setpos(int(start_t * wav_obj.getframerate()))
            # Read frames
            buf = wav_obj.readframes(int(self.chunk_len * wav_obj.getframerate()))

            k = self.kaldi_queue.get()
            k.push_chunk(buf)
            ret = k.get_final()
            k.reset()
            self.kaldi_queue.put(k)

            chunks.append({"start": start_t, "words": ret})
            logging.info('%d/%d' % (len(chunks), n_chunks))
            if progress_cb is not None:
                progress_cb({"message": ' '.join([X['word'] for X in ret]),
                             "percent": len(chunks) / float(n_chunks)})


        pool = Pool(min(n_chunks, self.nthreads))
        pool.map(transcribe_chunk, range(n_chunks))
        pool.close()
        
        chunks.sort(key=lambda x: x['start'])

        # Combine chunks
        # TODO: remove overlap? ...or just let the sequence aligner deal with it.
        words = []
        for c in chunks:
            chunk_start = c['start']
            for wd in c['words']:
                wd['start'] += chunk_start
                words.append(wd)

        return words

def to_json(tran, **kwargs):
    '''Return a JSON representation of the aligned transcript'''
    return json.dumps(tran, **kwargs)

def to_csv(tran):
    '''Return a CSV representation of the aligned transcript. Format:
    <word> <token> <start seconds> <end seconds>
    '''
    if not 'words' in tran:
        return ''
    buf = io.BytesIO()
    w = csv.writer(buf)
    for X in tran["words"]:
        if X.get("case") not in ("success", "not-found-in-audio"):
            continue
        row = [X["word"],
               X.get("alignedWord"),
               X.get("start"),
               X.get("end")
        ]
        w.writerow(row)
    return buf.getvalue()

if __name__=='__main__':
    # full transcription
    from Queue import Queue
    from gentle import ffmpeg
    from gentle import standard_kaldi
    import tempfile

    import sys

    import logging
    logging.getLogger().setLevel('INFO')
    
    k_queue = Queue()
    for i in range(3):
        k_queue.put(standard_kaldi.Kaldi())

    trans = MultiThreadedTranscriber(k_queue)

    with tempfile.NamedTemporaryFile(suffix='.wav') as fp:
        ffmpeg.to_wav(sys.argv[1], fp.name)

        out = trans.transcribe(fp.name)

    open(sys.argv[2], 'w').write(to_json(out))
