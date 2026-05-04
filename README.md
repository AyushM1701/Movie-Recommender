# CineMatch
https://cinematch-llrr.onrender.com

CineMatch is a movie recommendation web app. Instead of just filtering by genre, it uses machine learning to suggest movies based on their themes, cast, and crew. 

## Features
- **Smart Recommendations:** Uses natural language processing to find movies with a similar "feel".
- **Different Modes:** You can get recommendations based on specific genres, a few seed movies you select, or a hybrid of both.
- **User Accounts:** You can create an account, save movies to your personal library, and leave private ratings and notes.

## How it works (The Machine Learning part)
If you are interested in the math behind the recommendations, check out the `movie_recommender_concept.ipynb` file in this repository.

That Jupyter Notebook is the foundation of the project. It shows exactly how the raw datasets (from TMDB) are cleaned, how the text is vectorized using TF-IDF, and how the cosine similarity matrix is calculated to rank the movies.

## Tech Stack
- **Backend:** FastAPI (Python)
- **Frontend:** Plain HTML, CSS, and JavaScript
- **Database:** SQLite
- **Machine Learning:** scikit-learn, pandas, numpy

---

## How to run the project locally

1. Create and activate a virtual environment:

```bash
# On Windows
python -m venv .venv
.\.venv\Scripts\activate

# On macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

2. Install the required Python packages:

```bash
pip install -r backend/requirements.txt
```

3. Generate the Machine Learning models:
Because the machine learning models are too large to host on GitHub, you need to generate them on your computer first. Run this command to process the included CSVs and build the models (it takes about 60 seconds):

```bash
python backend/data_preprocessing.py
```

4. Start the application:

```bash
uvicorn backend.main:app --reload
```

5. Open your web browser and go to `http://127.0.0.1:8000/`

---

## Deployment
This project is set up on render https://cinematch-llrr.onrender.com

## Running Tests
To run the automated tests for the backend API:
```bash
python -m unittest backend.tests.test_api
```
