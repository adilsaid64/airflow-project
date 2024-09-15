# Carbon-Tracker-Airflow

This is an ETL pipeline project for processing and visualizing carbon intensity and generation data.

Carbon tracking is about keeping an eye on how much carbon dioxide (CO2) is being released into the atmosphere, especially when it comes to generating electricity. 

Carbon intensity tells us how much CO2 is produced for every unit of energy we use, while carbon generation shows us where our energy is coming from—whether it's from renewable sources like wind or solar, or fossil fuels like coal and gas. 

By tracking both, we can get a clearer picture of how clean or dirty our energy is and work towards reducing emissions.

- **ETL Orchestration**: Managed with Apache Airflow.
- **Data Visualization**: Created with Metabase.
- **Containerized**: Entire project runs in Docker for easy setup and deployment.


## Setup

1. Setup `.env` using  `.template.env`.
2. Run `docker-compose -f docker-compose.yml up --build -d --remove-orphans`

## Components
- **Airflow**: Orchestrates the ETL process.
- **MinIO**: Stores raw and processed data. AWS S3.
- **PostgreSQL**: Stores processed data.
- **Metabase**: Visualizes carbon data.
- **Celery**: Executes asynchronous and distributed tasks.
- **Redis**: Message broker for Celery.
- **Flower**: Web-based tool for monitoring Celery workers.

