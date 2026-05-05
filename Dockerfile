FROM python:3.10.4-alpine3.15

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN  apk update \
	&& apk add --no-cache gcc musl-dev postgresql-dev python3-dev libffi-dev \
	&& pip install --upgrade pip

COPY ./requirements.txt ./

RUN pip install -r requirements.txt

COPY ./ ./

EXPOSE 8005

CMD ["sh", "-c", "python src/manage.py collectstatic --noinput && python src/manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8005}"]
