# IBM Granite on LinuxONE (shift briefing writer)

`./run-granite.sh` starts IBM Granite inside IBM's own LinuxONE Community Cloud lab image (which
ships llama-cpp-python built for s390x and a big-endian Granite GGUF), behind a tiny
OpenAI-compatible server (`granite_server.py`, standard library only) on `127.0.0.1:8090`.
The agents use it with `SW_GRANITE_URL=http://127.0.0.1:8090`.

Honest limits: the model in IBM's image is Granite 4.0 H 350M **base** (not instruction-tuned),
so the agents give it the real facts and a fixed outline, check its output against those facts,
and fall back to a plain template (labelled as such) if Granite is slow, down, or adds anything
that is not in the facts. Granite only writes prose; it can never trigger an action.
