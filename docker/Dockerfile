FROM python:3.11-slim

# -- System deps per lxml, bs4, requests, ecc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libffi-dev \
    libssl-dev \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# -- Dir standard nel container
WORKDIR /app

# -- Copia requirements (prima dei bind mounts) per permettere il pip install in fase build
COPY app/requirements.txt /app/app/requirements.txt
COPY resolvers/requirements.txt /opt/external-resolvers/requirements.txt

# -- Installa dipendenze Python principali dell’app
RUN pip install --no-cache-dir -r /app/app/requirements.txt

# -- Installa dipendenze opzionali dei resolvers esterni (se presenti)
#    e in ogni caso installa "lxml" per evitare l'errore di BeautifulSoup.
RUN if [ -f /opt/external-resolvers/requirements.txt ]; then \
      pip install --no-cache-dir -r /opt/external-resolvers/requirements.txt; \
    fi && \
    pip install --no-cache-dir lxml

# -- Copie iniziali (verranno sovrascritte dai bind mounts a runtime, ma servono per build)
COPY app /app/app
COPY config /app/config
COPY resolvers /opt/external-resolvers

# -- Porta dell'app
EXPOSE 8791

# -- Avvio di default (puoi sovrascriverlo nel compose)
CMD ["uvicorn", "app.main:APP", "--host", "0.0.0.0", "--port", "8791", "--proxy-headers", "--forwarded-allow-ips", "*"]