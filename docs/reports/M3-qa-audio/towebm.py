import sys, av
src, dst = sys.argv[1], sys.argv[2]
inp = av.open(src)
out = av.open(dst, "w", format="webm")
st = out.add_stream("libopus", rate=48000)
st.layout = "mono"
res = av.AudioResampler(format="s16", layout="mono", rate=48000)
for frame in inp.decode(audio=0):
    for f in res.resample(frame):
        for p in st.encode(f): out.mux(p)
for f in res.resample(None):
    for p in st.encode(f): out.mux(p)
for p in st.encode(None): out.mux(p)
out.close(); inp.close()
