**Lunching the project**


 1. Install
pip install -r requirements.txt

 2. Configure
cp .env.example .env        # fill in your 3 keys

 3. Supabase — paste sql/schema.sql into the SQL Editor

 4. Verify chunking before burning API quota
python ingest.py --dry-run

 5. Ingest the PDF
python ingest.py

 6. Start the API
uvicorn api:app --reload
 → http://localhost:8000/docs