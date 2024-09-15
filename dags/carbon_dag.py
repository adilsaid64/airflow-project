from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.hooks.postgres_hook import PostgresHook
from datetime import datetime
import pandas as pd
import requests
import json
from typing import Optional, List, Callable
from tabulate import tabulate
import logging
from botocore.client import Config
import boto3
import io
from airflow.providers.postgres.hooks.postgres import PostgresHook

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

BASE_CARBON_URL = 'https://api.carbonintensity.org.uk'
GENERATION_BUCKET = 'generation-data'
INTENSITY_BUCKET = 'intensity-data'


CREATE_GENERATION_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS generation (
    id SERIAL PRIMARY KEY,
    fuel VARCHAR(50),
    perc NUMERIC(5, 2),
    from_time TIMESTAMPTZ,
    to_time TIMESTAMPTZ
);
"""

CREATE_INTENSITY_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS intensity (
    id SERIAL PRIMARY KEY,
    from_time TIMESTAMPTZ,
    to_time TIMESTAMPTZ,
    intensity_forecast INTEGER,
    intensity_actual INTEGER,
    intensity_index VARCHAR(20)
);
"""

QUERY_GENERATION = """
    INSERT INTO generation (fuel, perc, from_time, to_time)
    VALUES (%s, %s, %s, %s);
"""

QUERY_INTENSITY = """
    INSERT INTO intensity (from_time, to_time, intensity_forecast, intensity_actual, intensity_index)
    VALUES (%s, %s, %s, %s, %s);
"""


def get_data(url: str, headers: dict = {'Accept': 'application/json'}, params: dict = {}) -> dict:
    logger.info(f'Getting data from {url}')
    r = requests.get(url, params=params, headers=headers)
    return r.json()

def get_minio_client()->None:
    return boto3.client(
        's3',
        endpoint_url="http://minio:9000",
        aws_access_key_id="0m76fxtl7F3VJGM2bYzc",
        aws_secret_access_key="laJD5cHGNf9DrUVi1KiejgSzYObGzszNs60Kof7A",
        region_name='us-east-1'  # MinIO ignores region, but boto3 requires it
    )

def ensure_bucket_exists(s3_client:str, bucket_name:str):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except s3_client.exceptions.ClientError as e:
        if e.response['Error']['Code'] == '404':
            s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' created.")
        else:
            logger.error(f"Error checking or creating bucket: {e}")
            raise

def upload_to_minio(bucket_name:str, object_name:str, json_data:dict)->str:
    s3_client = get_minio_client()
    try:
        ensure_bucket_exists(s3_client, bucket_name)        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_name,
            Body=json.dumps(json_data),
            ContentType="application/json"
        )
        logger.info(f"Uploaded '{object_name}' to bucket '{bucket_name}'.")
        return object_name
    except Exception as err:
        logger.error(f"Error during upload: {err}")
        return repr(err)

def get_json_from_minio(bucket_name:str, object_name:str)->dict:
    s3_client = get_minio_client()
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_name)
        json_content = response['Body'].read().decode('utf-8')
        return json.loads(json_content)
    except s3_client.exceptions.NoSuchKey:
        logger.error(f"The object '{object_name}' does not exist in the bucket '{bucket_name}'.")
        return {}
    except Exception as err:
        logger.error(f"Error retrieving JSON from MinIO: {err}")
        return {}

def get_carbon_intensity_data(from_date:Optional[str]=None, **kwargs) -> str:
    if not from_date:
        execution_date = kwargs['execution_date'] 
        from_date = execution_date.strftime('%Y-%m-%d')  
    CARBON_INTENSITY_URL = f'{BASE_CARBON_URL}/intensity/date/{from_date}'
    intensity_data = get_data(url=CARBON_INTENSITY_URL)
    print(intensity_data)
    print(len(intensity_data['data']))
    minio_key = upload_to_minio(bucket_name=INTENSITY_BUCKET, object_name=f'{from_date}/raw.json', json_data=intensity_data)
    return minio_key

def get_carbon_generation_data(from_date:Optional[str]=None, **kwargs) -> str:
    if not from_date:
        execution_date = kwargs['execution_date']  
        from_date = execution_date.strftime('%Y-%m-%d')
    CARBON_GENERATION_URL = f'{BASE_CARBON_URL}/generation/{from_date}/pt24h'
    generation_data = get_data(url=CARBON_GENERATION_URL)
    minio_key = upload_to_minio(bucket_name=GENERATION_BUCKET, 
                                object_name=f'{from_date}/raw.json', 
                                json_data=generation_data)
    return minio_key

def process_carbon_intensity(intensity_data_key:str, **kwargs)->str:
    carbon_intensity_data = get_json_from_minio(bucket_name=INTENSITY_BUCKET, 
                                                object_name=intensity_data_key)
    df_intensity = pd.json_normalize(carbon_intensity_data['data'])
    print(tabulate(df_intensity, headers='keys', tablefmt='psql'))
    processed_key = upload_to_minio(bucket_name=INTENSITY_BUCKET, 
                                    object_name = f"{'/'.join(intensity_data_key.split('/')[:-1])}/processed.json", 
                                    json_data=df_intensity.to_dict(orient='records'))
    return processed_key

def process_carbon_generation(generation_data_key:str, **kwargs)->str:
    carbon_generation_data = get_json_from_minio(bucket_name=GENERATION_BUCKET, 
                                                 object_name=generation_data_key)
    
    df_generation = pd.json_normalize(data=carbon_generation_data['data'],
                                      record_path='generationmix',
                                      meta=['from', 'to'])
    
    print(tabulate(df_generation, headers='keys', tablefmt='psql'))

    processed_key = upload_to_minio(bucket_name=GENERATION_BUCKET, 
                                    object_name = f"{'/'.join(generation_data_key.split('/')[:-1])}/processed.json", 
                                    json_data=df_generation.to_dict(orient='records'))
    
    return processed_key


def insert_data_to_table(pg_hook:PostgresHook, query:str, records:List[dict], parameter_extractor:Callable):
    for record in records:
        try:
            parameters = parameter_extractor(record)
            pg_hook.run(query, parameters=parameters)
        except Exception as e:
            logger.error(f"Error inserting record {record}: {e}")

def extract_generation_parameters(record:dict)->list:
    return [record['fuel'], record['perc'], record['from'] ,record['to']]

def extract_intensity_parameters(record:dict)->list:
    return [record['from'], record['to'], 
            record['intensity.forecast'], 
            record['intensity.actual'], 
            record['intensity.index']]

def ensure_tables_exist(pg_hook:PostgresHook, create_table_query:str)->None:
    pg_hook.run(create_table_query)

def insert_into_postgres(bucket_name:str, processed_key:str, query:str, create_table_query:str, parameter_extractor:Callable, **kwargs)->None:
    pg_hook = PostgresHook(postgres_conn_id='carbon-postgres')
    ensure_tables_exist(pg_hook, create_table_query)
    processed_data = get_json_from_minio(bucket_name=bucket_name, 
                                                 object_name=processed_key)
    insert_data_to_table(pg_hook, query, processed_data, parameter_extractor)

def end():
    logger.info('DAG FINISHED!')

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 9, 10),
    'retries': 1,
}

with DAG('carbon_data_dag', default_args=default_args, schedule_interval='@daily', catchup=True) as dag:

    get_intensity_carbon_data = PythonOperator(
        task_id='get_intensity_carbon_data',
        python_callable=get_carbon_intensity_data,
        dag=dag
    )

    get_generation_carbon_data = PythonOperator(
        task_id='get_generation_carbon_data',
        python_callable=get_carbon_generation_data,
        dag=dag
    )

    process_intensity_task = PythonOperator(
        task_id='process_carbon_intensity',
        python_callable=process_carbon_intensity,
        op_kwargs={'intensity_data_key': '{{ ti.xcom_pull(task_ids="get_intensity_carbon_data") }}'},
        dag=dag
    )

    process_generation_task = PythonOperator(
        task_id='process_carbon_generation',
        python_callable=process_carbon_generation,
        op_kwargs={'generation_data_key': '{{ ti.xcom_pull(task_ids="get_generation_carbon_data") }}'},
        dag=dag
    )

    insert_generation_postgres_task = PythonOperator(
        task_id='insert_generation_postgres_task',
        python_callable=insert_into_postgres,
        op_kwargs={
            'bucket_name': GENERATION_BUCKET, 
            'processed_key': '{{ ti.xcom_pull(task_ids="process_carbon_generation") }}',
            'query' : QUERY_GENERATION,
            'create_table_query':CREATE_GENERATION_TABLE_QUERY,
            'parameter_extractor':extract_generation_parameters
        },
        dag=dag
    )

    insert_intensity_postgres_task = PythonOperator(
        task_id='insert_intensity_postgres_task',
        python_callable=insert_into_postgres,
        op_kwargs={
            'bucket_name': INTENSITY_BUCKET, 
            'processed_key': '{{ ti.xcom_pull(task_ids="process_carbon_intensity") }}',
            'query' : QUERY_INTENSITY,
            'create_table_query':CREATE_INTENSITY_TABLE_QUERY,
            'parameter_extractor':extract_intensity_parameters
        },
        dag=dag
    )


    end_dag = PythonOperator(
        task_id='end_dag',
        python_callable=end,
        dag=dag
    )

    get_intensity_carbon_data >> process_intensity_task >> insert_intensity_postgres_task
    get_generation_carbon_data >> process_generation_task >> insert_generation_postgres_task
    [insert_intensity_postgres_task, insert_generation_postgres_task] >> end_dag
