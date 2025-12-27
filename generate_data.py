import random
from datetime import datetime, timedelta

users = [1, 2, 3, 4]
start_date = datetime(2023, 1, 1)
end_date = datetime(2024, 12, 31)

sql_statements = []

for _ in range(150):  # Generate 150 orders for dense data
    user_id = random.choice(users)
    days_offset = random.randint(0, (end_date - start_date).days)
    order_date = start_date + timedelta(days=days_offset)
    amount = round(random.uniform(50, 500), 2)
    status = 'paid'
    
    date_str = order_date.strftime('%Y-%m-%d %H:%M:%S')
    sql = f"INSERT INTO orders (user_id, amount, status, created_at) VALUES ({user_id}, {amount}, '{status}', '{date_str}');"
    sql_statements.append(sql)

print("\n".join(sql_statements))
