import logging
import sqlite3
import time

dbname = "ancap.db"


def table_init():
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute('''CREATE TABLE if not exists current_pools (
                                    unique_id TEXT NOT NULL PRIMARY KEY,
                                    message_id INTEGER UNIQUE,
                                    type TEXT NOT NULL,
                                    counter_yes INTEGER,
                                    counter_no INTEGER,
                                    timer INTEGER,
                                    data TEXT NOT NULL,
                                    votes_need INTEGER);''')
    cursor.execute("""CREATE TABLE if not exists users_choise (
                                    message_id INTEGER,
                                    user_id INTEGER,
                                    choice TEXT);""")
    cursor.execute("""CREATE TABLE if not exists abuse (
                                    user_id INTEGER PRIMARY KEY,
                                    start_time INTEGER,
                                    timer INTEGER);""")
    cursor.execute("""CREATE TABLE if not exists whitelist (
                                    user_id INTEGER PRIMARY KEY);""")
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def deletion_of_overdue():
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""SELECT * FROM current_pools""")
    records = cursor.fetchall()
    for record in records:
        if record[5] + 600 < int(time.time()):
            rem_rec(record[1], record[0])
            logging.info('Removed deprecated poll "' + record[0] + '"')
    cursor.close()
    sqlite_connection.close()


def abuse_update(user_id):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""SELECT * FROM abuse WHERE user_id = ?""", (user_id,))
    record = cursor.fetchall()
    if not record:
        cursor.execute("""INSERT INTO abuse VALUES (?,?,?);""", (user_id, int(time.time()), 1800))
    else:
        cursor.execute("""UPDATE abuse SET start_time = ?, timer = ? WHERE user_id = ?""",
                       (int(time.time()), record[0][2] * 2, user_id))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def abuse_remove(user_id):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""DELETE FROM abuse WHERE user_id = ?""", (user_id,))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def abuse_check(user_id):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""SELECT * FROM abuse WHERE user_id = ?""", (user_id,))
    record = cursor.fetchall()
    if not record:
        return 0
    if record[0][1] + record[0][2] < int(time.time()):
        return 0
    else:
        return record[0][1] + record[0][2]


def whitelist(user_id, add=False, remove=False):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""SELECT * FROM whitelist WHERE user_id = ?""", (user_id,))
    fetchall = cursor.fetchall()
    is_white = False
    if fetchall:
        if remove:
            cursor.execute("""DELETE FROM whitelist WHERE user_id = ?""", (user_id,))
        else:
            is_white = True
    if add and not fetchall:
        cursor.execute("""INSERT INTO whitelist VALUES (?);""", (user_id,))
        is_white = True
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()
    return is_white


def addpool(unique_id, message_vote, pool_type, current_time, work_data, votes_need):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""INSERT INTO current_pools VALUES (?,?,?,?,?,?,?,?);""",
                   (unique_id, message_vote.id, pool_type, 0, 0, current_time, work_data, votes_need,))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def msg_chk(message_vote=None, unique_id=None):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    if message_vote is not None:
        cursor.execute("""SELECT * FROM current_pools WHERE message_id = ?""", (message_vote.message_id,))
    elif unique_id is not None:
        cursor.execute("""SELECT * FROM current_pools WHERE unique_id = ?""", (unique_id,))
    fetchall = cursor.fetchall()
    cursor.close()
    sqlite_connection.close()
    return fetchall


def rem_rec(message_id, unique_id=None):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    if unique_id is not None:
        cursor.execute("""DELETE FROM current_pools WHERE unique_id = ?""", (unique_id,))
    cursor.execute("""DELETE FROM users_choise WHERE message_id = ?""", (message_id,))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def is_user_voted(user_id, message_id):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""SELECT choice FROM users_choise WHERE user_id = ? AND message_id = ?""", (user_id, message_id,))
    fetchall = cursor.fetchall()
    cursor.close()
    sqlite_connection.close()
    if fetchall:
        return fetchall[0][0]
    return fetchall


def pool_update(counter_yes, counter_no, unique_id):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""UPDATE current_pools SET counter_yes = ?, counter_no = ? where unique_id = ?""",
                   (counter_yes, counter_no, unique_id))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def user_vote_update(call_msg):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""SELECT * FROM users_choise WHERE user_id = ? AND message_id = ?""",
                   (call_msg.from_user.id, call_msg.message.id,))
    record = cursor.fetchall()
    if not record:
        cursor.execute("""INSERT INTO users_choise VALUES (?,?,?)""",
                       (call_msg.message.id, call_msg.from_user.id, call_msg.data,))
    else:
        cursor.execute("""UPDATE users_choise SET choice = ? where message_id = ? AND user_id = ?""",
                       (call_msg.data, call_msg.message.id, call_msg.from_user.id))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()


def user_vote_remove(call_msg):
    sqlite_connection = sqlite3.connect(dbname)
    cursor = sqlite_connection.cursor()
    cursor.execute("""DELETE FROM users_choise WHERE message_id = ? AND user_id = ?""",
                   (call_msg.message.id, call_msg.from_user.id,))
    sqlite_connection.commit()
    cursor.close()
    sqlite_connection.close()
