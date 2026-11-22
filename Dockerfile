# PyLucene 10.0.0, Python 3.15, Java 21; build: docker build -t vinf-lucene - < Dockerfile
FROM coady/pylucene@sha256:4a37ca24019a9f1d2d94196323ccc8d7b465174d9229b2328429749989d4d05e
RUN pip install --no-cache-dir pytest requests
WORKDIR /work
