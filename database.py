import mysql.connector


def get_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="Brunda@2007",
        database="schememate"
    )

    return connection