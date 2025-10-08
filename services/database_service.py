import pymysql
import pymongo
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
import json
from datetime import datetime


class DatabaseConnector(ABC):
    """Abstract base class for database connectors"""

    def __init__(self, connection_config: Dict[str, Any]):
        self.connection_config = connection_config
        self.connection = None
        self.is_connected = False

    @abstractmethod
    def connect(self) -> bool:
        """Establish database connection"""
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Test database connection and return status"""
        pass

    @abstractmethod
    def get_tables(self) -> List[str]:
        """Get list of all tables/collections"""
        pass

    @abstractmethod
    def execute_query(self, query: str, table_name: str = None) -> Dict[str, Any]:
        """Execute query and return standardized result"""
        pass

    @abstractmethod
    def close(self):
        """Close database connection"""
        pass

    def __getstate__(self):
        """Exclude non-pickleable DB connection."""
        state = self.__dict__.copy()
        state['connection'] = None
        state['is_connected'] = False
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.connection = None
        self.is_connected = False

    def __str__(self):
        return f"config: {self.connection_config}\nconnection: {self.connection}\nstatus: {self.is_connected}"


class MySQLConnector(DatabaseConnector):
    """MySQL database connector"""

    type = 'mysql'

    def __init__(self, host: str, port: int, username: str, password: str, database: str):
        config = {
            'host': host,
            'port': port,
            'user': username,
            'password': password,
            'database': database
        }
        super().__init__(config)

    def connect(self) -> bool:
        """Establish MySQL connection"""
        try:
            self.connection = pymysql.connect(
                host=self.connection_config['host'],
                port=self.connection_config['port'],
                user=self.connection_config['user'],
                password=self.connection_config['password'],
                database=self.connection_config['database'],
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5,
                init_command="SET SESSION TRANSACTION READ ONLY"
            )
            self.is_connected = True
            return True
        except Exception as e:
            self.is_connected = False
            print(f"MySQL connection failed: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test MySQL connection"""
        try:
            if not self.is_connected:
                success = self.connect()
                if not success:
                    return {
                        'status': 'failed',
                        'database_type': 'mysql',
                        'message': 'Failed to establish connection',
                        'timestamp': datetime.now().isoformat()
                    }

            with self.connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            self.is_connected = True

            return {
                'status': 'success',
                'database_type': 'mysql',
                'message': 'Connection successful',
                'server_info': self.connection.get_server_info(),
                'database': self.connection_config['database'],
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'failed',
                'database_type': 'mysql',
                'message': f'Connection test failed: {str(e)}',
                'timestamp': datetime.now().isoformat()
            }

    def get_tables(self) -> List[str]:
        """Get list of all MySQL tables"""
        try:
            if not self.is_connected:
                self.connect()

            with self.connection.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                tables = [list(row.values())[0] for row in cursor.fetchall()]
                return tables
        except Exception as e:
            print(f"Error fetching tables: {e}")
            return []

    def execute_query(self, query: str, table_name: str = None) -> Dict[str, Any]:
        """Execute MySQL query"""
        try:
            if not self.is_connected:
                self.connect()

            with self.connection.cursor() as cursor:
                cursor.execute(query)
                data = cursor.fetchall()

                # Get table name from query if not provided
                if not table_name:
                    query_lower = query.lower()
                    if 'from' in query_lower:
                        table_name = query_lower.split(
                            'from')[1].strip().split()[0]

                return {
                    'table_names': [table_name] if table_name else ['unknown'],
                    'data': data,
                    'row_count': len(data),
                    'timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            return {
                'table_names': [],
                'data': [],
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def close(self):
        """Close MySQL connection"""
        if self.connection:
            self.connection.close()
            self.is_connected = False

    def __setstate__(self, state):
        super().__setstate__(state)
        # Optional: Reconnect immediately (can be disabled if needed)
        try:
            self.connect()
        except Exception as e:
            print(f"MySQL reconnect failed on load: {e}")


class MongoDBConnector(DatabaseConnector):
    """MongoDB database connector"""

    type = 'mongodb'

    def __init__(self, connection_uri: str, database: str = None):
        config = {
            'connection_uri': connection_uri,
            'database': database
        }
        super().__init__(config)
        self.database = None

    def connect(self) -> bool:
        """Establish MongoDB connection using connection URI"""
        try:
            self.connection = pymongo.MongoClient(
                self.connection_config['connection_uri'],
                serverSelectionTimeoutMS=5000,
                connect=False,
                maxPoolSize=1,
            )

            # Force connection check
            self.connection.admin.command('ping')

            db_name = self.connection_config['database']
            if db_name:
                # Check if database exists
                existing_dbs = self.connection.list_database_names()
                if db_name not in existing_dbs:
                    raise ValueError(f"MongoDB database '{
                                     db_name}' does not exist.")
                self.database = self.connection[db_name]

            self.is_connected = True
            return True
        except Exception as e:
            self.is_connected = False
            print(f"MongoDB connection failed: {e}")
            return False

    def test_connection(self) -> Dict[str, Any]:
        """Test MongoDB connection"""
        try:
            if not self.is_connected:
                success = self.connect()
                if not success:
                    return {
                        'status': 'failed',
                        'database_type': 'mongodb',
                        'message': 'Failed to establish connection',
                        'timestamp': datetime.now().isoformat()
                    }

            # Test connection by getting server info
            server_info = self.connection.server_info()

            self.is_connected = True
            return {
                'status': 'success',
                'database_type': 'mongodb',
                'message': 'Connection successful',
                'server_info': server_info['version'],
                'database': self.connection_config['database'],
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'failed',
                'database_type': 'mongodb',
                'message': f'Connection test failed: {str(e)}',
                'timestamp': datetime.now().isoformat()
            }

    def get_tables(self) -> List[str]:
        """Get list of all MongoDB collections"""
        try:
            if not self.is_connected:
                self.connect()
            print(self.database)
            if self.database == None:
                # If no specific database, list all databases
                databases = self.connection.list_database_names()
                return [f"database: {db}" for db in databases]

            collections = self.database.list_collection_names()
            return collections
        except Exception as e:
            print(f"Error fetching collections: {e}")
            return []

    def execute_query(self, query: str, collection_name: str = None) -> Dict[str, Any]:
        """Execute MongoDB query (expects JSON filter)"""
        try:
            if not self.is_connected:
                self.connect()

            print(self.database)
            print(self.is_connected)
            if self.database == None:
                return {
                    'table_names': [],
                    'data': [],
                    'error': 'No database selected',
                    'timestamp': datetime.now().isoformat()
                }

            # Parse query as JSON filter
            print(query)
            try:
                filter_dict = json.loads(query) if query.strip() else {}
            except json.JSONDecodeError as e:
                print(e)
                return {
                    'table_names': [],
                    'data': [],
                    'error': 'Invalid JSON filter',
                    'timestamp': datetime.now().isoformat()
                }

            if not collection_name:
                return {
                    'table_names': [],
                    'data': [],
                    'error': 'Collection name required',
                    'timestamp': datetime.now().isoformat()
                }

            collection = self.database[collection_name]
            cursor = collection.find(filter_dict)

            # Convert ObjectId to string for JSON serialization
            data = []
            for doc in cursor:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                data.append(doc)

            return {
                'table_names': [collection_name],
                'data': data,
                'row_count': len(data),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            print(e)
            return {
                'table_names': [],
                'data': [],
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def close(self):
        """Close MongoDB connection"""
        if self.connection:
            self.connection.close()
            self.is_connected = False

    def __getstate__(self):
        """Custom pickle state for MongoDB connector"""
        state = self.__dict__.copy()
        # Remove non-pickleable objects
        state['connection'] = None
        state['database'] = None
        state['is_connected'] = False
        return state

    def __setstate__(self, state):
        """Custom unpickle state for MongoDB connector"""
        self.__dict__.update(state)
        self.connection = None
        self.database = None
        self.is_connected = False
        # Optional: Reconnect immediately
        try:
            self.connect()
        except Exception as e:
            print(f"MongoDB reconnect failed on load: {e}")


class DatabaseCrawler:
    """Main database crawler class"""

    def __init__(self):
        self.connectors = {}

    def add_mysql_connection(self, name: str, host: str, port: int, username: str, password: str, database: str):
        """Add MySQL connection"""
        self.connectors[name] = MySQLConnector(
            host, port, username, password, database)

    def add_mongodb_connection(self, name: str, connection_uri: str, database: str = None):
        """Add MongoDB connection using connection URI"""
        self.connectors[name] = MongoDBConnector(connection_uri, database)

    def test_connection(self, connection_name: str) -> Dict[str, Any]:
        """Test specific connection"""
        if connection_name not in self.connectors:
            return {
                'status': 'failed',
                'message': f'Connection "{connection_name}" not found',
                'timestamp': datetime.now().isoformat()
            }

        return self.connectors[connection_name].test_connection()

    def get_tables(self, connection_name: str) -> List[str]:
        """Get tables for specific connection"""
        if connection_name not in self.connectors:
            return []

        return self.connectors[connection_name].get_tables()

    def execute_query(self, connection_name: str, query: str, table_name: str = None) -> Dict[str, Any]:
        """Execute query on specific connection"""
        if connection_name not in self.connectors:
            return {
                'table_names': [],
                'data': [],
                'error': f'Connection "{connection_name}" not found',
                'timestamp': datetime.now().isoformat()
            }

        return self.connectors[connection_name].execute_query(query, table_name)

    def close_all(self):
        """Close all connections"""
        for connector in self.connectors.values():
            connector.close()

    def __getstate__(self):
        """Custom pickle state for DatabaseCrawler"""
        return self.__dict__.copy()

    def __setstate__(self, state):
        """Custom unpickle state for DatabaseCrawler"""
        self.__dict__.update(state)

    def __str__(self):
        return f"{[name + ' : ' + str(connection) for name, connection in self.connectors.items()]}"


# Example usage and testing
if __name__ == "__main__":
    import pickle

    # Initialize crawler
    crawler = DatabaseCrawler()

    # Add connections
    crawler.add_mysql_connection(
        name="mysql_db",
        host="localhost",
        port=3306,
        username="bloguser",
        password="blogpass",
        database="blogdb"
    )

    crawler.add_mongodb_connection(
        name="mongo_db",
        host="localhost",
        port=27017,
        username=None,
        password=None,
        database="test_db"
    )

    # Test pickling
    print("Testing pickle functionality...")
    try:
        # Serialize
        pickled_data = pickle.dumps(crawler)
        print("✓ Pickling successful")

        # Deserialize
        unpickled_crawler = pickle.loads(pickled_data)
        print("✓ Unpickling successful")

        # Test that connections work after unpickling
        print("\nTesting connections after unpickling:")
        for name in unpickled_crawler.connectors.keys():
            result = unpickled_crawler.test_connection(name)
            print(f"{name}: {result['status']}")

    except Exception as e:
        print(f"✗ Pickle failed: {e}")

    # Close all connections
    crawler.close_all()
