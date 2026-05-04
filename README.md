# CineMatch

CineMatch is a movie recommendation app with:

- JWT-based sign-in and account creation
- genre, history, and hybrid recommendation modes
- a persistent personal library backed by SQLite
- notes and personal ratings for saved movies
- a single-page frontend served directly by FastAPI

## Run it

1. Activate the virtual environment:

```bash
# On Windows
.\.venv\Scripts\activate

# On macOS/Linux
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r backend/requirements.txt
```

3. Start the app from the project root:

```bash
uvicorn backend.main:app --reload
```

4. Open:

```text
http://127.0.0.1:8000/
```

## Test it

```bash
python -m unittest backend.tests.test_api
```

## Configuration

These environment variables are supported:

- `CINEMATCH_DATABASE_URL`
- `CINEMATCH_SECRET_KEY`
- `CINEMATCH_TOKEN_EXPIRE_DAYS`
- `CINEMATCH_CORS_ORIGINS`
