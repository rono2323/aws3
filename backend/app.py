import os
import json
import uuid
from datetime import datetime
from contextlib import contextmanager
from flask import Flask, request, jsonify, send_from_directory
from mysql.connector import pooling, Error as MySQLError

app = Flask(__name__, static_folder="static", static_url_path="")

# Environment variables and defaults
DBHOST = os.environ.get("DBHOST", "<url>.rds.amazonaws.com")
DBUSER = os.environ.get("DBUSER", "admin")
DBPASS = os.environ.get("DBPASS", "<pass>!")
DBNAME = os.environ.get("DBNAME", "elegancechocolat")
DBPORT = int(os.environ.get("DBPORT", 3306))
POOLNAME = os.environ.get("DBPOOLNAME", "mypool")
POOLSIZE = int(os.environ.get("DBPOOLSIZE", 5))
PORT = int(os.environ.get("PORT", 9090))

dbpool = None

def initdbpool():
    global dbpool
    if dbpool is None:
        print("Initializing MySQL connection pool...")
        dbpool = pooling.MySQLConnectionPool(
            pool_name=POOLNAME,
            pool_size=POOLSIZE,
            host=DBHOST,
            port=DBPORT,
            user=DBUSER,
            password=DBPASS,
            database=DBNAME,
            charset="utf8mb4"
        )

@contextmanager
def getdb():
    conn = None
    cursor = None
    try:
        conn = dbpool.get_connection()
        cursor = conn.cursor(dictionary=True)
        yield conn, cursor
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.commit()
            conn.close()

def ensuredatabaseandtables():
    try:
        import mysql.connector
        tmp = mysql.connector.connect(
            host=DBHOST, port=DBPORT, user=DBUSER, password=DBPASS
        )
        tmpcursor = tmp.cursor()
        tmpcursor.execute(
            f"CREATE DATABASE IF NOT EXISTS {DBNAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        tmpcursor.close()
        tmp.close()
        print("Database creation attempted or verified.")
    except Exception as e:
        print("Warning: DB creation attempt failed (often normal on managed RDS)", e)
    initdbpool()
    print("MySQL connection pool created at import time!")

    with getdb() as (conn, cursor):
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS products (
                   id VARCHAR(64) PRIMARY KEY,
                   name VARCHAR(255) NOT NULL,
                   price DECIMAL(10,2) NOT NULL,
                   flavor VARCHAR(255),
                   img TEXT
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                   orderid VARCHAR(64) PRIMARY KEY,
                   orderdate DATETIME NOT NULL,
                   totalamount DECIMAL(10,2) NOT NULL,
                   status VARCHAR(64) NOT NULL
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS orderitems (
                   itemid INT AUTO_INCREMENT PRIMARY KEY,
                   orderid VARCHAR(64) NOT NULL,
                   productid VARCHAR(64) NOT NULL,
                   productname VARCHAR(255) NOT NULL,
                   quantity INT NOT NULL,
                   unitprice DECIMAL(10,2) NOT NULL,
                   FOREIGN KEY(orderid) REFERENCES orders(orderid) ON DELETE CASCADE
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        print("Table/schema setup complete.")
        # Seed products if needed
        productsdata = [
            ("prod-001", "70% Dark Cacao Bar", 8.00, "Intense, deep, pure", "https://images.pexels.com/photos/6167328/pexels-photo-6167328.jpeg"),
            ("prod-002", "Sea Salt Dark Squares", 12.00, "Dark chocolate, sea salt flakes", "https://images.unsplash.com/photo-1504674900247-0877df9cc836"),
            ("prod-003", "Espresso Milk Bar", 10.00, "Smooth milk chocolate, espresso", "https://images.unsplash.com/photo-1504674900247-0877df9cc836"),
            ("prod-004", "White Raspberry Truffle", 14.00, "White chocolate, raspberry", "https://images.unsplash.com/photo-1527515637462-cff94eecc1ac"),
            ("prod-005", "Champagne Truffle", 17.00, "Milk chocolate, champagne", "https://images.pexels.com/photos/4399753/pexels-photo-4399753.jpeg"),
            ("prod-006", "Salted Caramel Praline", 16.00, "Milk chocolate, salted caramel", "https://images.pexels.com/photos/7676087/pexels-photo-7676087.jpeg")
        ]
        for pid, name, price, flavor, img in productsdata:
            cursor.execute(
                """INSERT INTO products (id, name, price, flavor, img)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE name=VALUES(name), price=VALUES(price), flavor=VALUES(flavor), img=VALUES(img)""",
                (pid, name, price, flavor, img)
            )

# Ensure DB/tables at app import
ensuredatabaseandtables()

@app.route("/health", methods=["GET"])
def healthcheck():
    return "Server is healthy!", 200

@app.route("/")
def serveindex():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/products", methods=["GET"])
def getproducts():
    with getdb() as (conn, cursor):
        cursor.execute("SELECT id, name, price, flavor, img FROM products")
        products = cursor.fetchall()
        categories = [
            {"id": 1, "name": "Dark Chocolate", "img": "https://images.pexels.com/photos/65882/chocolate-dark-coffee-confiserie-65882.jpeg", "flavors": ["70%Cacao", "Espresso", "Sea Salt", "Orange Zest"]},
            {"id": 2, "name": "Milk Chocolate", "img": "https://images.unsplash.com/photo-1504674900247-0877df9cc836", "flavors": ["Classic", "Hazelnut", "Caramel", "Almond"]},
            {"id": 3, "name": "Truffles & Pralines", "img": "https://images.pexels.com/photos/19121798/pexels-photo-19121798.jpeg", "flavors": ["Champagne", "Salted Caramel", "Tiramisu", "Rum"]}
        ]
        return jsonify({"categories": categories, "products": products})

@app.route("/api/checkout", methods=["POST"])
def checkout():
    data = request.get_json() or {}
    cartitems = data.get("items", [])
    if not cartitems:
        return jsonify({"message": "Cart is empty."}), 400
    productids = [item["id"] for item in cartitems]
    if not productids:
        return jsonify({"message": "No valid items."}), 400
    placeholders = ",".join(["%s"] * len(productids))
    try:
        with getdb() as (conn, cursor):
            cursor.execute(f"SELECT id, name, price FROM products WHERE id IN ({placeholders})", tuple(productids))
            productdetails = cursor.fetchall()
            productlookup = {p["id"]: p for p in productdetails}
            totalamount = 0.0
            orderitemstosave = []
            for item in cartitems:
                productid = item.get("id")
                quantity = int(item.get("qty", 0))
                if productid not in productlookup or quantity <= 0:
                    return jsonify({"message": "Invalid item or quantity found in cart."}), 400
                p = productlookup[productid]
                unitprice = float(p["price"])
                totalamount += unitprice * quantity
                orderitemstosave.append((productid, p["name"], quantity, unitprice))
            orderid = str(uuid.uuid4())
            orderdate = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            status = "Processing"
            cursor.execute(
                "INSERT INTO orders (orderid, orderdate, totalamount, status) VALUES (%s, %s, %s, %s)",
                (orderid, orderdate, totalamount, status)
            )
            for productid, productname, quantity, unitprice in orderitemstosave:
                cursor.execute(
                    "INSERT INTO orderitems (orderid, productid, productname, quantity, unitprice) VALUES (%s, %s, %s, %s, %s)",
                    (orderid, productid, productname, quantity, unitprice)
                )
            return jsonify({"orderId": orderid, "status": status, "total": round(totalamount, 2), "message": "Order placed successfully!"}), 200
    except MySQLError as e:
        print("Database error during checkout", e)
        return jsonify({"message": "Server encountered a database error. Please try again."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
