FROM python:3.10-slim

WORKDIR /app

COPY web /app/web
COPY dag.py /app/
COPY owl.py /app/

ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y graphviz

RUN pip install --no-cache-dir flask requests graphviz owlready2 Pillow dot2tex

EXPOSE 5000

ENV FLASK_APP=web/app.py
ENV FLASK_ENV=development

CMD ["flask", "run", "--host=0.0.0.0"]