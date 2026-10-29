import os

# OpenBLAS's own thread pool can deadlock on Windows when several Python threads (request handlers,
# background analysis) multiply matrices at once. Ours are tiny, so one BLAS thread costs nothing.
# Must be set before numpy is first imported.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(_var, "1")
