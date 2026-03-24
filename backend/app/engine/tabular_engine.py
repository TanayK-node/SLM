from sqlalchemy import create_engine, inspect, text
import os
from app.engine.model import generate_response
from app.engine.sql_engine import connect_to_database
import pandas as pd


def process_file_to_db(file_path: str, filename: str):
    """Reads a CSV/Excel file and converts it into a queryable SQLite database."""
    try:
        # 1. Read the file using Pandas
        if filename.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path)
        else:
            return False, "Unsupported file format. Please upload a .csv or .xlsx file."

        # 2. Clean the column names (SQL hates spaces and weird characters)
        df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_').str.replace(r'[^\w\s]', '', regex=True)

        # 3. Create a temporary SQLite database in the root folder
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_path = os.path.join(root_dir, "temp_spreadsheet.db")
        
        # Remove the old temp database if it exists so we start fresh
        if os.path.exists(db_path):
            os.remove(db_path)
            
        temp_engine = create_engine(f"sqlite:///{db_path}")

        # 4. Dump the Pandas DataFrame into the SQLite database
        table_name = "uploaded_data"
        df.to_sql(table_name, temp_engine, index=False, if_exists='replace')

        # 5. Plug our AI SQL Engine into this new temporary database!
        success, msg = connect_to_database(f"sqlite:///{db_path}")
        
        if success:
            return True, f"Successfully processed {filename}. The AI is ready to analyze the '{table_name}' table."
        else:
            return False, "Failed to connect AI to the temporary database."
            
    except Exception as e:
        return False, f"Error processing file: {str(e)}"
    
async def ask_spreadsheet(user_query: str, history_text: str = ""):
    """A specialized SQL engine just for analyzing the uploaded spreadsheet."""
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(root_dir, "temp_spreadsheet.db")
    
    if not os.path.exists(db_path):
        return "Please upload a CSV or Excel file first before asking data questions."
        
    # Connect to the temporary spreadsheet database
    temp_engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(temp_engine)
    
    # Get the columns of the uploaded file
    columns = inspector.get_columns("uploaded_data")
    schema_info = "Table: uploaded_data\nColumns:\n"
    for col in columns:
        schema_info += f"  - {col['name']} ({col['type']})\n"
        
    # The Data Scientist Prompt
    csv_prompt = f"""
    You are an expert Data Scientist analyzing an uploaded spreadsheet.
    The spreadsheet has been converted into a SQLite table named 'uploaded_data'.
    
    === SPREADSHEET COLUMNS ===
    {schema_info}
    
    === RULES ===
    1. Output ONLY the raw SQL query. No markdown.
    2. Use SQLite syntax.
    3. You can use mathematical functions like AVG(), SUM(), MAX(), MIN(), and COUNT().
    === PREVIOUS CONVERSATION CONTEXT ===
    {history_text}
    User Question: {user_query}
    """
    
    raw_sql = await generate_response(csv_prompt)
    clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()
    print(f"📊 CSV Engine Generated SQL: {clean_sql}")
    
    try:
        with temp_engine.connect() as connection:
            result = connection.execute(text(clean_sql))
            rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]
            
        synthesis_prompt = f"""
        You are a helpful Data Analyst. The user asked: "{user_query}"
        The spreadsheet data returned: {rows}
        
        Answer the user's question clearly based ONLY on this data. Do not hallucinate.
        """
        return await generate_response(synthesis_prompt)
        
    except Exception as e:
        return f"Error analyzing spreadsheet: {str(e)}"