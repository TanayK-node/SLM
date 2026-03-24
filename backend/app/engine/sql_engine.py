import os
import re # <--- ADD THIS LINE
from sqlalchemy import create_engine, inspect, text
from app.engine.model import generate_response

# Global state for the active database connection
db_engine = None
db_dialect = "Unknown"

def connect_to_database(connection_string: str):
    """The Plug-and-Play connector. Accepts any valid SQLAlchemy URL."""
    global db_engine, db_dialect
    try:
        # Create the new engine
        new_engine = create_engine(connection_string)
        
        # Test the connection to ensure the credentials are valid
        with new_engine.connect() as conn:
            pass 
            
        # If successful, update the global state
        db_engine = new_engine
        db_dialect = db_engine.dialect.name
        return True, f"Successfully connected to {db_dialect.upper()} database!"
    except Exception as e:
        return False, f"Failed to connect: {str(e)}"

def get_database_schema():
    if db_engine is None:
        return "No database is currently connected."
        
    inspector = inspect(db_engine)
    schema_info = ""
    
    for table_name in inspector.get_table_names():
        schema_info += f"Table: {table_name}\nColumns:\n"
        for column in inspector.get_columns(table_name):
            schema_info += f"  - {column['name']} ({column['type']})\n"
        schema_info += "\n"
        
    return schema_info

async def ask_database(user_query: str, history_text: str = ""):
    schema = get_database_schema()
    
    # 1. Ask for SQL, but expect it to be chatty
    sql_prompt = f"""
    You are an expert SQL Data Analyst.
    Translate the User Question into a highly accurate {db_dialect.upper()} query based on the schema.
    
    Database Schema:
    {schema}
    === PREVIOUS CONVERSATION CONTEXT ===
    {history_text}
    User Question: {user_query}
    
    CRITICAL INSTRUCTION: You MUST output ONLY the SQL query wrapped in a ```sql block. Do not provide explanations, assumptions, or any other text.
    """
    
    raw_sql = await generate_response(sql_prompt)
    
    # 2. INTELLIGENT PARSING: Use Regex to extract ONLY the code inside the ```sql block
    match = re.search(r"```(?:sql)?(.*?)```", raw_sql, re.DOTALL | re.IGNORECASE)
    if match:
        clean_sql = match.group(1).strip()
    else:
        # Fallback if it didn't use markdown
        clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()
        # Strip out any trailing explanations
        if "Explanation:" in clean_sql:
            clean_sql = clean_sql.split("Explanation:")[0].strip()
            
    print(f"\n🔍 Cleaned SQL for DB: {clean_sql}")
    
    try:
        if any(forbidden in clean_sql.upper() for forbidden in ["DROP", "DELETE", "UPDATE", "INSERT"]):
            return "Security Alert: Query contains forbidden modification commands."
            
        # 3. Execute the strictly cleaned SQL safely
        with db_engine.connect() as connection:
            result = connection.execute(text(clean_sql))
            columns = result.keys()
            formatted_data = [dict(zip(columns, row)) for row in result.fetchall()]
            
        print(f"📊 Formatted DB Rows returned: {formatted_data}")
            
        # 4. FIXED SYNTHESIS PROMPT: Force a human-friendly answer ONLY
        synthesis_prompt = f"""
        You are a helpful, professional Data Analyst communicating with a business user.
        The user asked: "{user_query}"
        
        You ran a database query which returned this exact raw data:
        {formatted_data}
        
        INSTRUCTIONS:
        1. Provide a direct, human-friendly conversational answer to the user's question using ONLY the data above.
        2. DO NOT show any SQL code. DO NOT explain how you got the answer. DO NOT make assumptions.
        3. If the data returns a count, just state the count clearly.
        
        Answer:
        """
        
        final_answer = await generate_response(synthesis_prompt)
        return final_answer

        
    except Exception as e:
        return f"I encountered an error running the database query: {str(e)}"

        
    except Exception as e:
        return f"I encountered an error running the database query: {str(e)}"