import pymysql
import json
from datetime import date

def json_serial(obj):
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError ("Type not serializable")

def verify():
    # Try localhost since we are on the host/agent machine, mapped from docker
    conn = pymysql.connect(
        host='127.0.0.1',
        port=3306,
        user='root',
        password='123456',
        database='cv_cp',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    sql = """
    SELECT 
        MONTH(order_date) as month,
        city,
        SUM(amount) as total_amount
    FROM orders
    GROUP BY city, MONTH(order_date)
    ORDER BY city, month
    """
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            result = cursor.fetchall()
            print("--- Database Ground Truth ---")
            print(json.dumps(result, default=json_serial, ensure_ascii=False, indent=2))
    finally:
        conn.close()

if __name__ == "__main__":
    verify()
