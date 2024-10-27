# Cinderbackend

## Description
Cinderbackend is the backend service for the Cinder project, which aims to provide a platform for data analysis result management and sharing of Proteomics-based Mass Spectrometry data.

## Development Requirements
- Python 3.10 or higher
- Poetry for dependency management
- Docker and Docker Compose

## Main Dependencies
- Django
- Django REST Framework
- PostgreSQL
- Redis
- Channels
- Gunicorn

## Development Installation

### Manual Installation

1. **Clone the repository:**
    ```sh
    git clone https://github.com/noatgnu/cinderbackend.git
    cd cinderbackend
    ```

2. **Install dependencies using Poetry:**
    ```sh
    poetry install
    ```

3. **Activate the virtual environment:**
    ```sh
    poetry shell
    ```

4. **Apply database migrations:**
    ```sh
    python manage.py migrate
    ```

5. **Run the development server:**
    ```sh
    python manage.py runserver
    ```

### Docker Installation

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

## Setup with Let's Encrypt

1. **Clone the repository:**
    ```sh
    git clone https://github.com/noatgnu/cinderbackend.git
    cd cinderbackend
    ```

2. **Build and start the containers with Let's Encrypt:**
    ```sh
    docker-compose -f docker-compose.letsencrypt.yml up --build -d
    ```

3. **Apply database migrations:**
    ```sh
    docker-compose -f docker-compose.letsencrypt.yml exec cinderbackend python manage.py migrate
    ```

4. **Create a superuser (optional):**
    ```sh
    docker-compose -f docker-compose.letsencrypt.yml exec -it cinderbackend python manage.py createsuperuser
    ```

5. **Access the development server:**
    The development server will be available at `https://yourdomain.com`.

## Environment Variables

Create a `.env` file in the root directory of the project and set the following environment variables:

```env
POSTGRES_NAME=postgres
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=dbcinderbackend
REDIS_HOST=rediscinderbackend
CORS_ORIGIN_WHITELIST=http://localhost,http://localhost:4200,http://172.31.0.5
ALLOWED_HOSTS=localhost,172.31.0.5,localhost:8000
VIRTUAL_HOST=api.yourdomain.com
LETSENCRYPT_HOST=api.yourdomain.com
LETSENCRYPT_EMAIL=your-email@example.com
```

Create a `frontend.env` file in the root directory of the project and set the following environment variables:

```env
VIRTUAL_HOST=yourdomain.com
LETSENCRYPT_HOST=yourdomain.com
LETSENCRYPT_EMAIL=your-email@example.com
```

Replace `yourdomain.com` and `your-email@example.com` with your actual domain and email address.

## Setup with Ansible

1. **Clone the repository:**
    ```sh
    git clone https://github.com/noatgnu/cinderbackend.git
    cd cinderbackend
    ```

2. **Run the Ansible playbook for Let's Encrypt setup:**
    ```sh
    ansible-playbook playbooks/docker.letsencrypt.ansible.yml
    ```

3. **Access the development server:**
    The development server will be available at `https://yourdomain.com`.

## License
This project is licensed under the MIT License.
