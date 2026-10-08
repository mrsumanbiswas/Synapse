# Read-only demo FTP server holding sample datasets (arXiv CSV + raw text papers).
FROM docker.io/library/python:3.14-alpine
RUN pip install --no-cache-dir pyftpdlib==2.2.0 \
    && adduser -D -u 10002 ftpuser
COPY server.py /srv/server.py
COPY data /srv/ftp
USER ftpuser
EXPOSE 2121 30000-30009
CMD ["python", "/srv/server.py"]
