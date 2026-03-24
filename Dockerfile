FROM python:3.13-bullseye

RUN groupadd -r baymax && useradd -r -g baymax baymax

WORKDIR /home/baymax/app


ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN python3 -m venv env
ENV PATH="/home/baymax/app/env/bin:$PATH"

RUN pip install -r requirements.txt

COPY . .


CMD [ "/home/baymax/app/env/bin/gunicorn", "-w 4", "-b 0.0.0.0:5000", "app:app"]
