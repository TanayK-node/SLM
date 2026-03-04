import os
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

async def ask_database(user_query: str):
    schema = get_database_schema()
    
    # IMPROVEMENT 1: Few-Shot Prompting
    # We give the small model a few examples of how to map tricky English to SQL.
    sql_prompt = f"""
    You are an expert SQL Data Analyst.
    Your task is to translate the User Question into a highly accurate {db_dialect.upper()} query.
    
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
            
        # 2. Execute the SQL safely
        with db_engine.connect() as connection:
            result = connection.execute(text(clean_sql))
            
            # IMPROVEMENT 1: Map column names to the row values
            # This turns [(2,)] into [{'count(*)': 2}] 
            # or [('Alice', 'Senior Quant')] into [{'name': 'Alice', 'role': 'Senior Quant'}]
            columns = result.keys()
            formatted_data = [dict(zip(columns, row)) for row in result.fetchall()]
            
        print(f"📊 Formatted DB Rows returned: {formatted_data}")
            
        # IMPROVEMENT 2: Updated Synthesis Prompt
        synthesis_prompt = f"""
        You are a highly accurate data reporter.
        You are an expert SQL Data Analyst.
        Given the following database schema, write a SQL query for the SQLite database to answer the user's question.
        The user asked: "{user_query}"
        
        The database returned the following exact data:
        {formatted_data}
        
        RULES:
        1. Answer the user's question STRICTLY based on the provided data. 
        2. Do not hallucinate numbers. Do not guess. 
        3. If the data shows a single dictionary like {{'COUNT(*)': 2}}, it means the total count is 2.
        4. Make the answer sound natural and professional.
        
        Answer:
        """
        
        final_answer = await generate_response(synthesis_prompt)
        return final_answer

        
    except Exception as e:
        return f"I encountered an error running the database query: {str(e)}"