# Cinderbackend

## Description
Cinderbackend is the backend service for Cinder project which aims to provide a platform for data analysis result management and sharing of Proteomics-based Mass Spectrometry data.

## Development Requirements
- Python 3.10 or higher
- Poetry for dependency management

### Main Dependencies
```shell
python = "^3.10"
django = "^5.0.6"
django-cors-headers = "^4.3.1"
pandas = "^2.2.2"
django-filter = "^24.2"
psycopg2-binary = "^2.9.9"
channels = "^4.1.0"
channels-redis = {extras = ["cryptography"], version = "^4.2.0"}
uvicorn = {extras = ["standard"], version = "^0.30.0"}
websockets = "^12.0"
whitenoise = "^6.6.0"
requests = "^2.32.3"
httpx = "^0.27.0"
djangorestframework = "^3.15.1"
django-rq = "^2.10.2"
drf-chunked-upload = "^0.6.0"
django-redis = "^5.4.0"
django-dbbackup = "^4.1.0"
gunicorn = "^22.0.0"
curtainutils = "^0.1.16"
```

## Development Installation (manual)

1. Clone the repository:
    ```sh
    git clone https://github.com/noatgnu/cinderbackend.git
    cd cinderbackend
    ```

2. Install dependencies using Poetry:
    ```sh
    poetry install
    ```

3. Activate the virtual environment:
    ```sh
    poetry shell
    ```
4. Apply database migrations:
    ```sh
    python manage.py migrate
    ```

5. Run the development server:
    ```sh
    python manage.py runserver
    ```

## Setup with Docker

1. **Clone the repository:**
    ```sh
    git clone https://github.com/noatgnu/cinderbackend.git
    cd cinderbackend
    ```

2. **Build and start the containers:**
    ```sh
    docker-compose up --build
    ```

3. **Apply database migrations:**
    ```sh
    docker-compose exec cinderbackend python manage.py migrate
    ```

4. **Create a superuser (optional):**
    ```sh
    docker-compose exec -it cinderbackend python manage.py createsuperuser
    ```

5. **Access the development server:**
    The development server will be available at `http://localhost:8000`.

## License
This project is licensed under the MIT License.
