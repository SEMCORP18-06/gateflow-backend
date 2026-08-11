from pymongo import MongoClient

user = "enquiry_db_user"
password = "FJND34ouaoPsNCby"
cluster = "cluster0.rr0husv.mongodb.net"

uri = f"mongodb+srv://{user}:{password}@{cluster}/?retryWrites=true&w=majority"
print(f"Testing MongoDB Atlas connection with username '{user}'...")

try:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    print("SUCCESS! Connected & authenticated to MongoDB Atlas cluster0!")
except Exception as e:
    print(f"Failed to connect: {e}")
