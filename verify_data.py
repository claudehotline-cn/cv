import sqlalchemy
from sqlalchemy import create_engine, text
import pandas as pd

# Connection string (assuming default from docker-compose)
db_url = "mysql+pymysql://root:123456@mysql:3306/cv_cp?charset=utf8mb4"

try:
    engine = create_engine(db_url)
    with engine.connect() as connection:
        sql = """
        SELECT 
            DATE_FORMAT(m_orders.created_at, '%Y-%m') AS month, 
            m_cities.name AS city, 
            SUM(m_orders.amount) AS total_amount 
        FROM m_orders 
        INNER JOIN m_customers ON m_orders.customer_id = m_customers.id 
        INNER JOIN m_cities ON m_customers.city_id = m_cities.id 
        WHERE m_cities.name IN ('北京', '上海') AND YEAR(m_orders.created_at) = 2024 
        GROUP BY month, city 
        ORDER BY month, city
        """
        result = connection.execute(text(sql))
        rows = result.fetchall()
        
        print(f"{'Month':<10} | {'City':<10} | {'Amount':<10}")
        print("-" * 35)
        for row in rows:
            print(f"{row[0]:<10} | {row[1]:<10} | {row[2]}")
            
except Exception as e:
    print(f"Error: {e}")
