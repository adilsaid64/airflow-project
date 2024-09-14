FROM apache/airflow:2.10.1

COPY requirements.txt /opt/airflow/

USER root
RUN apt-get update && apt-get install -y gcc python3-dev

USER airflow

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /opt/airflow/requirements.txt