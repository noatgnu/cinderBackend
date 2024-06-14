FROM python:3.10-bullseye
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN curl https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor | tee /etc/apt/trusted.gpg.d/apt.postgresql.org.gpg > /dev/null
RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt bullseye-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
RUN apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 7FCC7D46ACCC4CF8
RUN apt-get update
RUN apt-get -y install postgresql-client-14
WORKDIR /app
RUN mkdir "/app/media"
RUN mkdir "/app/staticfiles"
RUN mkdir "/app/backup"
COPY . /app/

RUN pip install -r requirements.txt
RUN python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn","--workers=3", "cinderBackend.asgi:application", "--bind", "0.0.0.0:8000","--timeout", "300", "-k", "uvicorn.workers.UvicornWorker"]