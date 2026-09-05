import sqlite3
import random
from datetime import datetime, timedelta

def create_mock_database():
    db_name = "data/enterprise.db"
    print(f"🛠️ Creating mock database at {db_name}...")
    
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # 1. Create Departments Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )''')

    # 2. Create Employees Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        department_id INTEGER,
        FOREIGN KEY (department_id) REFERENCES departments (id)
    )''')

    # 3. Create Users (Customers) Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        state TEXT NOT NULL,
        signup_date DATE NOT NULL
    )''')

    # 4. Create Orders Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        employee_id INTEGER,
        amount REAL,
        status TEXT,
        order_date DATE,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    )''')

    # --- POPULATE MOCK DATA ---
    
    # Insert Departments
    depts = ['Sales', 'Engineering', 'Marketing', 'HR', 'Support']
    for d in depts:
        cursor.execute("INSERT INTO departments (name) VALUES (?)", (d,))

    # Insert Employees
    employees = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Frank', 'Grace', 'Hank']
    for emp in employees:
        dept_id = random.randint(1, 5)
        cursor.execute("INSERT INTO employees (name, department_id) VALUES (?, ?)", (emp, dept_id))

    # Insert Users
    states = ['CA', 'NY', 'TX', 'FL', 'WA']
    base_date = datetime.now() - timedelta(days=60)
    for i in range(1, 51): # 50 users
        signup = base_date + timedelta(days=random.randint(0, 60))
        cursor.execute("INSERT INTO users (username, state, signup_date) VALUES (?, ?, ?)", 
                       (f"user_{i}", random.choice(states), signup.strftime('%Y-%m-%d')))

    # Insert Orders
    statuses = ['Completed', 'Pending', 'Failed']
    for i in range(1, 101): # 100 orders
        user_id = random.randint(1, 50)
        emp_id = random.randint(1, 8)
        amount = round(random.uniform(50.0, 5000.0), 2)
        status = random.choices(statuses, weights=[0.7, 0.2, 0.1])[0]
        order_date = base_date + timedelta(days=random.randint(0, 60))
        
        cursor.execute('''INSERT INTO orders (user_id, employee_id, amount, status, order_date) 
                          VALUES (?, ?, ?, ?, ?)''', 
                       (user_id, emp_id, amount, status, order_date.strftime('%Y-%m-%d')))

    conn.commit()
    conn.close()
    print("✅ Database created and populated successfully!")

if __name__ == "__main__":
    create_mock_database()