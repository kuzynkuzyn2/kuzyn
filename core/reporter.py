"""
Ten moduł można użyć aby raportować akcje do pliku lub zdalnego serwera MySQL
"""
import logging
import time
import warnings

try:
    import pymysql

    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False


class RemoteReporter:
    """
    Klasa bazowa dla obiektu raportera
    """
    def report(self, connection, village_id, action, data):
        """
        Ustawia dane raportu
        """
        return

    def add_data(self, connection, village_id, data_type, data):
        """
        Ustawia dane specyficzne dla typu
        """
        return

    def get_config(self, connection, village_id, action, data):
        """
        Pobiera konfigurację z raportera
        """
        return

    def setup(self, connection):
        """
        Konfiguruj reporter
        """
        return


class FileReporter:
    """
    Reporter, który zapisuje dane do pliku tekstowego
    """
    def report(self, connection, village_id, action, data):
        """
        Zapisuje wpis do pliku raportu
        """
        with open(connection, 'a', encoding="utf-8") as f:
            f.write("%d - %s - %s - %s\n" % (time.time(), village_id, action, data))
        return

    def add_data(self, connection, village_id, data_type, data):
        """
        Nieużywane dla tego typu
        """
        return

    def get_config(self, connection, village_id, action, data):
        """
        Nieużywane dla tego typu
        """
        return

    def setup(self, connection):
        """
        Upewnia się, że plik logów istnieje
        """
        with open(connection, 'w', encoding="utf-8") as f:
            f.write("Uruchomiono bota o %d\n" % time.time())


class MySQLReporter(RemoteReporter):
    """
    Używa (zdalnego) serwera MySQL do logowania
    """
    @staticmethod
    def connection_from_object(cobj):
        """
        Pobiera zmienne z konfiguracji połączenia
        """
        return pymysql.connect(
            host=cobj['host'],
            port=cobj['port'],
            user=cobj['user'],
            password=cobj['password'],
            database=cobj['database'])

    def report(self, connection, village_id, action, data):
        """
        Dodaje wpis raportu
        """
        con = MySQLReporter.connection_from_object(connection)
        cur = con.cursor()
        cur.execute("INSERT INTO twb_logs (village, action, data, ts) VALUES (%s, %s, %s, NOW())",
                    (village_id, action, data))
        con.commit()
        cur.close()
        con.close()

    def add_data(self, connection, village_id, data_type, data):
        """
        Zapisuje dane na zdalnym serwerze MySQL
        """
        con = self.connection_from_object(connection)
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM twb_data WHERE village_id = %s AND data_type = %s",
            (village_id, data_type)
        )
        if cur.rowcount > 0:
            cur.execute(
                "UPDATE twb_data SET data = %s, last_update = NOW() WHERE village_id = %s AND data_type = %s",
                (data, village_id, data_type)
            )
        else:
            cur.execute(
                "INSERT INTO twb_data (village_id, data_type, data, last_update) VALUES (%s, %s, %s, NOW())",
                (village_id, data_type, data)
            )
        con.commit()
        cur.close()
        con.close()

    def setup(self, connection):
        """
        Tworzy początkowe tabele bazy danych
        """
        try:
            con = self.connection_from_object(connection)
            query_data = """CREATE TABLE IF NOT EXISTS `twb_data` (
                    `id`  int NOT NULL AUTO_INCREMENT ,
                    `village_id`  int NULL ,
                    `data_type`  varchar(50) NULL ,
                    `data`  text NULL ,
                    `last_update`  datetime NULL ,
                    PRIMARY KEY (`id`)
                    )"""
            query_logs = """CREATE TABLE IF NOT EXISTS `twb_logs` (
                            `id`  int NOT NULL AUTO_INCREMENT ,
                            `village_id`  int NULL ,
                            `action`  varchar(50) NULL ,
                            `data`  text NULL ,
                            `ts`  datetime NULL ,
                            PRIMARY KEY (`id`)
                            )"""
            cur = con.cursor()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cur.execute(query_data)
                cur.execute(query_logs)
                con.commit()
            cur.close()
            con.close()
            return True
        except Exception as e:
            print(f"MYSQL ERROR: {e}")
            return False


class ReporterObject:
    """
    Bazowy obiekt raportujący dla zdalnego/lokalnego loggera
    """
    enabled = False
    object = None
    logger = logging.getLogger("RemoteLogger")
    connection = None

    def __init__(self, enabled=False, connection_string=None):
        """
        Wykrywa konfigurację raportera
        """
        if enabled and connection_string:
            self.enabled = True
            self.setup(connection_string=connection_string)

    def setup(self, connection_string):
        """
        Pobiera używany reporter
        """
        if connection_string.startswith('mysql://'):
            if not HAS_PYMYSQL:
                self.logger.error("pymysql jest wymagany do logowania MYSQL\nZainstaluj go używając pip install pymysql")
                self.enabled = False
                return

            parameters = connection_string.split('://')[1]
            creds, host_and_db = parameters.split('@')
            username, password = creds.split(':')
            host, database = host_and_db.split('/')
            port = 3306
            if ":" in host:
                host, port = host.split(":")
                port = int(port)
            self.connection = {"host": host, "port": port, "user": username, "password": password, "database": database}
            self.object = MySQLReporter()
            if self.object.setup(self.connection):
                self.logger.info("Konfiguracja MySQL zakończona pomyślnie")
            else:
                self.logger.info("Nie można skonfigurować logowania MySQL, wyłączam!")
                self.enabled = False
        elif connection_string.startswith('file://'):
            outfile = connection_string.split("://")[1]
            outfile = outfile.replace('{ts}', str(int(time.time())))
            self.connection = outfile
            self.object = FileReporter()
            self.object.setup(self.connection)
        else:
            self.object = RemoteReporter()

    def report(self, village_id, action, data):
        """
        Uruchamia funkcję raportującą zainstalowanego raportera
        """
        if self.enabled:
            return self.object.report(self.connection, village_id, action, data)
        return

    def add_data(self, village_id, data_type, data):
        """
        Uruchamia funkcję add_data zainstalowanego raportera
        """
        if self.enabled:
            return self.object.add_data(self.connection, village_id, data_type, data)
        return

    def get_config(self, village_id, action, data):
        """
        Uruchamia funkcję get_config zainstalowanego raportera
        """
        if self.enabled:
            return self.object.get_config(self.connection, village_id, action, data)
        return
