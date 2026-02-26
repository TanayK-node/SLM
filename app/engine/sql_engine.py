# engine/sql_engine.py
from sqlalchemy import create_engine, inspect, text
from app.engine.model import generate_response
import os 

# 1. Get the absolute path of the current file (sql_engine.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
# 2. Go up two levels to reach the root SLM-AI folder
root_dir = os.path.dirname(os.path.dirname(current_dir))
# 3. Join it with the database file name
db_path = os.path.join(root_dir, "company_data.db")
# 4. Create the final SQLite URL


DB_URL = f"sqlite:///{db_path}"
db_engine = create_engine(DB_URL)

# Connect to our local SQLite DB (Companies would put their Postgres URL here)

def get_database_schema():
    """Extracts the table names and columns so the LLM knows what to query."""
    inspector = inspect(db_engine)
    schema_info = ""
    
    for table_name in inspector.get_table_names():
        schema_info += f"Table: {table_name}\nColumns:\n"
        for column in inspector.get_columns(table_name):
            schema_info += f"  - {column['name']} ({column['type']})\n"
        schema_info += "\n"
        
    return schema_info

async def ask_database(user_query: str):
    schema = get_database_schema()
    
    # IMPROVEMENT 1: Few-Shot Prompting
    # We give the small model a few examples of how to map tricky English to SQL.
    sql_prompt = f"""
    You are an expert SQL Data Analyst.
    Given the following database schema, write a SQL query for the SQLite database to answer the user's question.
    
    Database Schema:
    {schema}
    
    EXAMPLES:
    User: "Are any algorithms losing money?"
    SQL: SELECT algo_name, total_profit FROM algorithm_performance WHERE total_profit < 0;
    
    User: "How many algorithms are in each status?"
    SQL: SELECT status, COUNT(*) FROM algorithm_performance GROUP BY status;
    
    User Question: {user_query}
    
    CRITICAL: Output ONLY the raw SQL query. Do not include any markdown formatting like ```sql or explanations. Just the SQL code.
    """
    
    raw_sql = await generate_response(sql_prompt)
    clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()
    print(f"\n🔍 Generated SQL: {clean_sql}")
    
    try:
        if any(forbidden in clean_sql.upper() for forbidden in ["DROP", "DELETE", "UPDATE", "INSERT"]):
            return "Security Alert: Query contains forbidden modification commands."
            
        with db_engine.connect() as connection:
            result = connection.execute(text(clean_sql))
            rows = result.fetchall()
            
        # IMPROVEMENT 2: Terminal Debugging
        # Look at this print statement in your terminal when you test! 
        # It tells you if the SQL worked correctly.
        print(f"📊 Raw DB Rows returned: {rows}")
            
        # IMPROVEMENT 3: Strict Synthesis Prompt
        synthesis_prompt = f"""
        You are a highly accurate data reporter. 
        The user asked: "{user_query}"
        The database returned this exact data: {rows}
        
        RULES:
        1. Answer the user's question STRICTLY based on the provided data list. 
        2. Do not hallucinate numbers. Do not guess. 
        3. If the data shows a negative number, state that it is losing money.
        4. Make the answer sound natural and professional.
        
        Answer:
        """
        
        final_answer = await generate_response(synthesis_prompt)
        return final_answer
        
    except Exception as e:
        return f"I encountered an error running the database query: {str(e)}"