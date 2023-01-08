import logging
import os
import pickle
import random
import threading
import time
import traceback

import telebot

import utils
import postvote

functions = {
    "invite": (postvote.vote_result_useradd, "инвайт пользователя"),
    "ban": (postvote.vote_result_userkick, "блокировка пользователя"),
    "unban": (postvote.vote_result_unban, "снятие ограничений с пользователя"),
    "threshold": (postvote.vote_result_treshold, "смена порога голосов для стандартных опросов"),
    "threshold for ban votes": (postvote.vote_result_treshold_ban, "смена порога голосов для бан-опросов"),
    "timer": (postvote.vote_result_timer, "смена таймера для стандартных опросов"),
    "timer for ban votes": (postvote.vote_result_timer, "смена таймера для бан-опросов"),
    "delete message": (postvote.vote_result_delmsg, "удаление сообщения"),
    "op": (postvote.vote_result_op, "назначение администратора"),
    "deop": (postvote.vote_result_deop, "снятие администратора"),
    "title": (postvote.vote_result_title, "смена названия чата"),
    "chat picture": (postvote.vote_result_chat_pic, "смена аватарки чата"),
    "description": (postvote.vote_result_description, "смена описания чата"),
    "rank": (postvote.vote_result_rank, "смена звания бота"),
    "captcha": (postvote.vote_result_new_usr, "капча"),
    "change rate": (postvote.vote_result_change_rate, "изменение рейтинга"),
    "add allies": (postvote.vote_result_add_allies, "добавление союзного чата"),
    "remove allies": (postvote.vote_result_remove_allies, "удаление союзного чата"),
    "timer for random cooldown": (postvote.vote_result_random_cooldown, "изменение кулдауна команды /random"),
    "whitelist": (postvote.vote_result_whitelist, "редактирование вайтлиста")
}


def vote_result(unique_id, message_vote):
    global functions
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if not records:
        return

    if records[0][1] != message_vote.id:
        return

    try:
        os.remove(utils.PATH + unique_id)
    except IOError:
        logging.error("Failed to clear a pool file!")
        logging.error(traceback.format_exc())

    sqlWorker.rem_rec(message_vote.id, unique_id)
    utils.auto_thresholds_init()
    votes_counter = "\nЗа: " + str(records[0][3]) + "\n" + "Против: " + str(records[0][4])
    if records[0][3] > records[0][4] and records[0][3] > utils.minimum_vote:
        accept = True
    elif records[0][3] + records[0][4] > utils.minimum_vote:
        accept = False
    else:
        accept = False
        votes_counter = "\nНедостаточно голосов (требуется как минимум " + str(utils.minimum_vote + 1) + ")"

    try:
        functions[records[0][2]][0](records, message_vote, votes_counter, accept)
    except KeyError:
        logging.error(traceback.format_exc())
        utils.bot.edit_message_text("Ошибка применения результатов голосования. Итоговая функция не найдена!",
                                    message_vote.chat.id, message_vote.id)
    except Warning:  # Пусть не срёт в логи после clearmsg
        return

    try:
        utils.bot.unpin_chat_message(utils.main_chat_id, message_vote.message_id)
    except telebot.apihelper.ApiTelegramException:
        logging.error(traceback.format_exc())

    try:
        utils.bot.reply_to(message_vote, "Оповещение о закрытии голосования.")
    except telebot.apihelper.ApiTelegramException:
        logging.error(traceback.format_exc())

    utils.update_conf()
    

def auto_restart_pools():
    time_now = int(time.time())
    records = sqlWorker.get_all_pools()
    for record in records:
        try:
            pool = open(utils.PATH + record[0], 'rb')
            message_vote = pickle.load(pool)
            pool.close()
        except (IOError, pickle.UnpicklingError):
            logging.error(f"Failed to read a pool {record[0]}!")
            logging.error(traceback.format_exc())
            continue
        if record[5] > time_now:
            threading.Thread(target=vote_timer, args=(record[5] - time_now, record[0], message_vote)).start()
            logging.info("Restarted poll " + record[0])
        else:
            vote_result(record[0], message_vote)


def vote_timer(current_timer, unique_id, message_vote):
    time.sleep(current_timer)
    utils.vote_abuse.clear()
    vote_result(unique_id, message_vote)


sqlWorker = utils.sqlWorker
utils.init()
auto_restart_pools()


def pool_constructor(unique_id: str, vote_text: str, message, vote_type: str, current_timer: int, current_votes: int,
                     vote_args: list, user_id: int, adduser=False, silent=False):
    vote_text = "{}\nГолосование будет закрыто через {}, " \
                "для досрочного завершения требуется голосов за один из пунктов: {}.\n" \
                "Минимальный порог голосов для принятия решения: {}." \
        .format(vote_text, utils.formatted_timer(current_timer), str(current_votes), str(utils.minimum_vote + 1))

    message_vote = utils.vote_make(vote_text, message, adduser, silent)
    sqlWorker.addpool(unique_id, message_vote, vote_type,
                       int(time.time()) + current_timer, str(vote_args), current_votes, user_id)
    utils.pool_saver(unique_id, message_vote)
    threading.Thread(target=vote_timer, args=(current_timer, unique_id, message_vote)).start()


@utils.bot.message_handler(commands=['invite'])
def add_usr(message):
    if not utils.botname_checker(message):
        return

    if not utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status in ("left", "kicked",
                                                                                          "restricted") \
            or utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).is_member:
        # Fuuuuuuuck my brain
        utils.bot.reply_to(message, "Вы уже есть в нужном вам чате.")
        return

    unique_id = str(message.from_user.id) + "_useradd"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    abuse_chk = sqlWorker.abuse_check(message.from_user.id)
    if abuse_chk > 0:
        utils.bot.reply_to(message, "Сработала защита от абуза инвайта! Вам следует подождать ещё "
                           + utils.formatted_timer(abuse_chk - int(time.time())))
        return

    if sqlWorker.whitelist(message.from_user.id):
        sqlWorker.abuse_remove(message.from_user.id)
        sqlWorker.abuse_update(message.from_user.id)
        invite = utils.bot.create_chat_invite_link(utils.main_chat_id, expire_date=int(time.time()) + 86400)
        utils.bot.reply_to(message, f"Вы получили личную ссылку для вступления в чат, так как находитесь в вайтлисте.\n"
                                    "Ссылка истечёт через 1 сутки.\n"
                           + invite.invite_link)
        return

    try:
        msg_from_usr = message.text.split(None, 1)[1]
    except IndexError:
        msg_from_usr = "нет"

    vote_text = ("Тема голосования: заявка на вступление от пользователя <a href=\"tg://user?id="
                 + str(message.from_user.id) + "\">" + utils.username_parser(message, True) + "</a>.\n"
                 + "Сообщение от пользователя: " + msg_from_usr + ".")

    # vote_text = ("Пользователь " + "[" + utils.username_parser(message)
    # + "](tg://user?id=" + str(message.from_user.id) + ")" + " хочет в чат.\n"
    # + "Сообщение от пользователя: " + msg_from_usr + ".")

    pool_constructor(unique_id, vote_text, message, "invite", utils.global_timer, utils.votes_need,
                     [message.chat.id, utils.username_parser(message)], message.from_user.id, adduser=True)

    warn = ""
    if utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status == "kicked":
        warn = "\nВнимание! Вы были заблокированы в чате ранее, поэтому вероятность инвайта минимальная!"
    if utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status == "restricted":
        warn = "\nВнимание! Сейчас на вас распространяются ограничения прав в чате, выданные командой /mute!"
    utils.bot.reply_to(message, "Голосование о вступлении отправлено в чат. Голосование завершится через "
                       + utils.formatted_timer(utils.global_timer) + " или ранее." + warn)


@utils.bot.message_handler(commands=['answer'])
def add_answer(message):
    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Пожалуйста, используйте эту команду как ответ на заявку на вступление")
        return

    pool = sqlWorker.msg_chk(message_vote=message.reply_to_message)
    if pool:
        if pool[0][2] != "invite":
            utils.bot.reply_to(message, "Данное голосование не является голосованием о вступлении.")
            return
    else:
        utils.bot.reply_to(message, "Заявка на вступление не найдена или закрыта.")
        return

    try:
        msg_from_usr = message.text.split(None, 1)[1]
    except IndexError:
        utils.bot.reply_to(message, "Ответ не может быть пустым.")
        return

    datalist = eval(pool[0][6])

    try:
        utils.bot.send_message(datalist[0], "Сообщение на вашу заявку от участника чата - \"" + msg_from_usr + "\"")
        utils.bot.reply_to(message, "Сообщение пользователю отправлено успешно.")
    except telebot.apihelper.ApiTelegramException:
        logging.error(traceback.format_exc())
        utils.bot.reply_to(message, "Ошибка отправки сообщению пользователю.")


@utils.bot.message_handler(commands=['ban', 'kick'])
def ban_usr(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Ответьте на сообщение пользователя, которого требуется забанить.")
        return

    user_id, username, _ = utils.reply_msg_target(message.reply_to_message)

    restrict_timer = 0
    if utils.extract_arg(message.text, 1) is not None:
        restrict_timer = utils.time_parser(utils.extract_arg(message.text, 1))
        if restrict_timer is None:
            utils.bot.reply_to(message,
                               "Некорректный аргумент времени (не должно быть меньше 31 секунды и больше 365 суток).")
            return
        if not 30 < restrict_timer <= 31536000:
            utils.bot.reply_to(message, "Время не должно быть меньше 31 секунды и больше 365 суток.")
            return

        if 31535991 <= restrict_timer <= 31536000:
            restrict_timer = 31535990

    kickuser = True if restrict_timer != 0 else False

    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "left" and kickuser:
        utils.bot.reply_to(message, "Пользователя нет в чате, чтобы можно было кикнуть его.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "creator":
        utils.bot.reply_to(message, "Я думаю, ты сам должен понимать тщетность своих попыток.")
        return

    if utils.bot.get_me().id == user_id:
        utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return

    unique_id = str(user_id) + "_userban"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    ban_timer_text = "\nПредложенный срок блокировки: <b>перманентный</b>" if restrict_timer == 0 else \
        f"\nПредложенный срок блокировки: {utils.formatted_timer(restrict_timer)}"
    vote_type = 1 if kickuser else 2

    vote_theme = "блокировка пользователя"
    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "kicked":
        vote_theme = "изменение срока блокировки пользователя"

    date_unban = ""
    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "kicked":
        until_date = utils.bot.get_chat_member(utils.main_chat_id, user_id).until_date
        if until_date == 0 or until_date is None:
            date_unban = "\nПользователь был ранее заблокирован перманентно"
        else:
            date_unban = "\nДо разблокировки пользователя оставалось " \
                         + utils.formatted_timer(until_date - int(time.time()))

    vote_text = (f"Тема голосования: {vote_theme} {username}" + date_unban + ban_timer_text +
                 f"\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, "ban", utils.global_timer_ban, utils.votes_need_ban,
                     [user_id, username, utils.username_parser(message), vote_type, restrict_timer],
                     message.from_user.id)


@utils.bot.message_handler(commands=['mute'])
def mute_usr(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Ответьте на имя пользователя, которого требуется замутить.")
        return

    user_id, username, _ = utils.reply_msg_target(message.reply_to_message)

    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "kicked":
        utils.bot.reply_to(message, "Данный пользователь уже забанен или кикнут.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "creator":
        utils.bot.reply_to(message, "Я думаю, ты сам должен понимать тщетность своих попыток.")
        return

    if utils.bot.get_me().id == user_id:
        utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return

    restrict_timer = 0
    if utils.extract_arg(message.text, 1) is not None:
        restrict_timer = utils.time_parser(utils.extract_arg(message.text, 1))
        if restrict_timer is None:
            utils.bot.reply_to(message, "Некорректный аргумент времени "
                                        "(должно быть меньше 31 секунды и больше 365 суток).")
            return
        if not 30 < restrict_timer <= 31536000:
            utils.bot.reply_to(message, "Время не должно быть меньше 31 секунды и больше 365 суток.")
            return

    if 31535991 <= restrict_timer <= 31536000:
        restrict_timer = 31535990

    unique_id = str(user_id) + "_userban"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    ban_timer_text = "\nПредложенный срок ограничений: перманентно" if restrict_timer == 0 else \
        f"\nПредложенный срок ограничений: {utils.formatted_timer(restrict_timer)}"

    vote_theme = "ограничение сообщений пользователя"
    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "restricted":
        vote_theme = "изменение срока ограничения сообщений пользователя"

    date_unban = ""
    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "restricted":
        until_date = utils.bot.get_chat_member(utils.main_chat_id, user_id).until_date
        if until_date == 0 or until_date is None:
            date_unban = "\nПользователь был ранее заблокирован перманентно"
        else:
            date_unban = "\nДо разблокировки пользователя оставалось " \
                         + utils.formatted_timer(until_date - int(time.time()))

    vote_text = (f"Тема голосования: {vote_theme} {username}" + date_unban + ban_timer_text
                 + f"\nИнициатор голосования: {utils.username_parser(message, True)}.")

    vote_type = 0
    pool_constructor(unique_id, vote_text, message, "ban", utils.global_timer_ban, utils.votes_need_ban,
                     [user_id, username, utils.username_parser(message), vote_type, restrict_timer],
                     message.from_user.id)


@utils.bot.message_handler(commands=['unmute', 'unban'])
def unban_usr(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Ответьте на имя пользователя, которого требуется размутить или разбанить.")
        return

    user_id, username, _ = utils.reply_msg_target(message.reply_to_message)

    if utils.bot.get_me().id == user_id:
        utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status != "restricted" and \
            utils.bot.get_chat_member(utils.main_chat_id, user_id).status != "kicked":
        utils.bot.reply_to(message, "Данный пользователь не ограничен.")
        return

    unique_id = str(user_id) + "_unban"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    vote_text = ("Тема голосования: снятие ограничений с пользователя " + username
                 + f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, "unban", utils.global_timer, utils.votes_need,
                     [user_id, username, utils.username_parser(message)], message.from_user.id)


@utils.bot.message_handler(commands=['threshold'])
def thresholds(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    mode = utils.extract_arg(message.text, 1)
    if mode is None:
        auto_thresholds_mode = "" if not utils.auto_thresholds else " (автоматический режим)"
        auto_thresholds_ban_mode = "" if not utils.auto_thresholds_ban else " (автоматический режим)"
        utils.auto_thresholds_init()
        utils.bot.reply_to(message, "Текущие пороги:\nГолосов для обычного решения требуется: " + str(utils.votes_need)
                           + auto_thresholds_mode + "\n"
                           + "Голосов для бана требуется: " + str(utils.votes_need_ban) + auto_thresholds_ban_mode
                           + "\n" + "Минимальный порог голосов для принятия решения: " + str(utils.minimum_vote + 1))
        return
    unique_id = "threshold"
    bantext = "стандартных голосований"
    if utils.extract_arg(message.text, 2) == "ban":
        unique_id = "threshold for ban votes"
        bantext = "бан-голосований"

    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    if mode != "auto":
        try:
            mode = int(mode)
        except (TypeError, ValueError):
            utils.bot.reply_to(message, "Неверный аргумент (должно быть целое число от 2 до "
                               + str(utils.bot.get_chat_members_count(utils.main_chat_id)) + " или \"auto\").")
            return

        if mode > utils.bot.get_chat_members_count(utils.main_chat_id):
            utils.bot.reply_to(message,
                               "Количество необходимых голосов не может быть больше количества участников в чате.")
            return

        if mode <= utils.minimum_vote:
            utils.bot.reply_to(message, "Количество необходимых голосов не может быть меньше "
                               + str(utils.minimum_vote + 1))
            return

        vote_text = (f"Тема голосования: установка порога голосов {bantext} на значение {str(mode)}"
                     f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

    else:
        vote_text = (f"Тема голосования: установка порога голосов {bantext} на автоматически выставляемое значение"
                     f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, unique_id, utils.global_timer, utils.votes_need,
                     [mode], message.from_user.id)


@utils.bot.message_handler(commands=['timer'])
def timer(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id == message.from_user.id:
        utils.bot.reply_to(message, "Данную команду невозможно запустить в личных сообщениях.")
        return

    timer_arg = utils.extract_arg(message.text, 1)
    if timer_arg is None:
        timer_text = ""
        if message.chat.id == utils.main_chat_id:
            timer_text = utils.formatted_timer(utils.global_timer) + " для обычного голосования.\n" \
                         + utils.formatted_timer(utils.global_timer_ban) + " для голосования за бан.\n"
        if sqlWorker.abuse_random(message.chat.id) == -1:
            timer_random_text = "Команда /random отключена."
        elif sqlWorker.abuse_random(message.chat.id) == 0:
            timer_random_text = "Кулдаун команды /random отключён."
        else:
            timer_random_text = utils.formatted_timer(sqlWorker.abuse_random(message.chat.id)) \
                                + " - кулдаун команды /random."
        utils.bot.reply_to(message, "Текущие пороги таймера:\n" + timer_text + timer_random_text)
        return

    if utils.extract_arg(message.text, 2) is None:
        unique_id = "timer"
        bantext = "таймера стандартных голосований"
        timer_arg = utils.time_parser(timer_arg)
        if timer_arg is None:
            utils.bot.reply_to(message, "Неверный аргумент (должно быть число от 5 секунд до 1 суток).")
            return
        elif timer_arg < 5 or timer_arg > 86400:
            utils.bot.reply_to(message, "Количество времени не может быть меньше 5 секунд и больше 1 суток.")
            return
        elif timer_arg == utils.global_timer:
            utils.bot.reply_to(message, "Это значение установлено сейчас!")
            return
    elif utils.extract_arg(message.text, 2) == "ban":
        unique_id = "timer for ban votes"
        bantext = "таймера бан-голосований"
        timer_arg = utils.time_parser(timer_arg)
        if timer_arg is None:
            utils.bot.reply_to(message, "Неверный аргумент (должно быть число от 5 секунд до 1 суток).")
            return
        elif timer_arg < 5 or timer_arg > 86400:
            utils.bot.reply_to(message, "Количество времени не может быть меньше 5 секунд и больше 1 суток.")
            return
        elif timer_arg == utils.global_timer_ban:
            utils.bot.reply_to(message, "Это значение установлено сейчас!")
            return
    elif utils.extract_arg(message.text, 2) == "random":
        unique_id = "timer for random cooldown"
        bantext = "кулдауна команды /random"
        timer_arg = utils.time_parser(timer_arg)
        if utils.extract_arg(message.text, 1) == "off":
            timer_arg = -1
        if timer_arg is None:
            utils.bot.reply_to(message, "Неверный аргумент (должно быть число от 0 секунд до 1 часа).")
            return
        elif timer_arg < -1 or timer_arg > 3600:
            utils.bot.reply_to(message, "Количество времени не может быть меньше 0 секунд и больше 1 часа.")
            return
        elif timer_arg == sqlWorker.abuse_random(message.chat.id):
            utils.bot.reply_to(message, "Это значение установлено сейчас!")
            return
    else:
        utils.bot.reply_to(message, "Неверный второй аргумент (должен быть ban, random или пустой).")
        return

    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    if timer_arg == -1:
        vote_text = (f"Тема голосования: отключение команды /random."
                     f"\nИнициатор голосования: {utils.username_parser(message, True)}.")

    elif timer_arg == 0:
        vote_text = (f"Тема голосования: отключение кулдауна команды /random."
                     f"\nИнициатор голосования: {utils.username_parser(message, True)}.")
    else:
        vote_text = (f"Тема голосования: смена {bantext} на значение "
                     + utils.formatted_timer(timer_arg) +
                     f"\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, unique_id, utils.global_timer, utils.votes_need,
                     [timer_arg, unique_id], message.from_user.id)


def rate_top(message):
    whitelist_msg = utils.bot.reply_to(message, "Сборка рейтинга, ожидайте...")
    rates = sqlWorker.get_all_rates()
    if rates is None:
        utils.bot.reply_to(message, "Ещё ни у одного пользователя нет социального рейтинга!")
        return

    for k in range(0, len(rates)):
        for j in range(0, len(rates) - 1):
            if rates[j][1] < rates[j + 1][1]:
                rates[j], rates[j + 1] = rates[j + 1], rates[j]

    rate_text = "Список пользователей по социальному рейтингу:"
    user_counter = 1

    for user_rate in rates:
        if utils.bot.get_chat_member(utils.main_chat_id, user_rate[0]).status == "kicked" \
                or utils.bot.get_chat_member(utils.main_chat_id, user_rate[0]).status == "left":
            sqlWorker.clear_rate(user_rate[0])
            continue
        username = utils.username_parser_chat_member(utils.bot.get_chat_member(utils.main_chat_id, user_rate[0]), True)
        rate_text = rate_text + f'\n{user_counter}. ' \
                                f'<a href="tg://user?id={user_rate[0]}">{username}</a>: {str(user_rate[1])}'
        user_counter += 1

    utils.bot.edit_message_text(rate_text, chat_id=whitelist_msg.chat.id,
                                message_id=whitelist_msg.id, parse_mode='html')


@utils.bot.message_handler(commands=['rate'])
def rating(message):
    if not utils.botname_checker(message) or not utils.rate:
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    mode = utils.extract_arg(message.text, 1)

    if mode is None:
        if message.reply_to_message is None:
            user_id, username, _ = utils.reply_msg_target(message)
        else:
            if utils.bot.get_me().id == message.reply_to_message.from_user.id:
                utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
                return

            user_status = utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).status

            if user_status == "kicked" or user_status == "left":
                sqlWorker.clear_rate(message.reply_to_message.from_user.id)
                utils.bot.reply_to(message, "Этот пользователь не является участником чата.")
                return

            user_id, username, is_bot = utils.reply_msg_target(message.reply_to_message)
            if is_bot:
                utils.bot.reply_to(message, "У ботов нет социального рейтинга!")
                return

        user_rate = sqlWorker.get_rate(user_id)
        utils.bot.reply_to(message, f"Социальный рейтинг пользователя {username}: {user_rate}")
        return

    if mode == "top":
        threading.Thread(target=rate_top, args=(message,)).start()
        return

    if mode == "up" or mode == "down":

        if message.reply_to_message is None:
            utils.bot.reply_to(message, "Пожалуйста, ответьте на сообщение пользователя, "
                                        "чей социальный рейтинг вы хотите изменить")
            return

        user_id, username, is_bot = utils.reply_msg_target(message.reply_to_message)

        if user_id == message.from_user.id:
            utils.bot.reply_to(message, "Вы не можете менять свой собственный рейтинг!")
            return

        if user_id == utils.bot.get_me().id:
            utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            return

        if is_bot:
            utils.bot.reply_to(message, "У ботов нет социального рейтинга!")
            return

        if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "kicked" \
                or utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "left":
            sqlWorker.clear_rate(user_id)
            utils.bot.reply_to(message, "Этот пользователь не является участником чата.")
            return

        unique_id = str(user_id) + "_rating_" + mode
        records = sqlWorker.msg_chk(unique_id=unique_id)
        if utils.is_voting_exists(records, message, unique_id):
            return

        mode_text = "увеличение" if mode == "up" else "уменьшение"

        vote_text = (f"Тема голосования: {mode_text} "
                     f"социального рейтинга пользователя {username}"
                     f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

        pool_constructor(unique_id, vote_text, message, "change rate", utils.global_timer, utils.votes_need,
                         [username, message.reply_to_message.from_user.id,
                          mode, utils.username_parser(message)], message.from_user.id)
        return

    utils.bot.reply_to(message, "Неправильные аргументы (доступны top, up, down и команда без аргументов).")


@utils.bot.message_handler(commands=['status'])
def status(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    target_msg = message
    if message.reply_to_message is not None:
        target_msg = message.reply_to_message

    statuses = {"left": "покинул группу",
                "kicked": "заблокирован",
                "restricted": "ограничен",
                "creator": "автор чата",
                "administrator": "администратор",
                "member": "участник"}

    user_id, username, is_bot = utils.reply_msg_target(target_msg)

    if is_bot:
        whitelist_status = "является ботом"
    elif sqlWorker.whitelist(target_msg.from_user.id):
        whitelist_status = "да"
    else:
        whitelist_status = "нет"

    until_date = ""
    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status in ("kicked", "restricted"):
        if utils.bot.get_chat_member(utils.main_chat_id, user_id).until_date == 0:
            until_date = "\nОсталось до снятия ограничений: ограничен бессрочно"
        else:
            until_date = "\nОсталось до снятия ограничений: " + \
                         str(utils.formatted_timer(utils.bot.get_chat_member(utils.main_chat_id, user_id)
                                                   .until_date - int(time.time())))

    utils.bot.reply_to(message, f"Текущий статус пользователя {username}"
                                f" - {statuses.get(utils.bot.get_chat_member(utils.main_chat_id, user_id).status)}"
                                f"\nНаличие в вайтлисте: {whitelist_status}{until_date}")


def whitelist_building(message, whitelist):
    whitelist_msg = utils.bot.reply_to(message, "Сборка вайтлиста, ожидайте...")
    user_list, counter = "Список пользователей, входящих в вайтлист:\n", 1
    for user in whitelist:
        try:
            username = utils.username_parser_chat_member(utils.bot.get_chat_member(utils.main_chat_id,
                                                                                   user[0]), html=True)
            if username == "":
                sqlWorker.whitelist(user[0], remove=True)
                continue
        except telebot.apihelper.ApiTelegramException:
            logging.error(traceback.format_exc())
            sqlWorker.whitelist(user[0], remove=True)
            continue
        user_list = user_list + f'{counter}. <a href="tg://user?id={user[0]}">{username}</a>\n'
        counter = counter + 1

    utils.bot.edit_message_text(user_list
                                + "Узнать подробную информацию о конкретном пользователе можно командой /status",
                                chat_id=whitelist_msg.chat.id, message_id=whitelist_msg.id, parse_mode='html')


@utils.bot.message_handler(commands=['whitelist'])
def status(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    if utils.extract_arg(message.text, 1) in ("add", "remove"):

        if message.reply_to_message is not None:
            who_id, who_name, is_bot = utils.reply_msg_target(message.reply_to_message)
        else:
            who_id, who_name, is_bot = utils.reply_msg_target(message)

        if utils.extract_arg(message.text, 2) is not None and utils.extract_arg(message.text, 1) == "remove":

            whitelist = sqlWorker.whitelist_get_all()
            if not whitelist:
                utils.bot.reply_to(message, "Вайтлист данного чата пуст!")
                return

            try:
                index = int(utils.extract_arg(message.text, 2)) - 1
                if index < 0:
                    raise ValueError
            except ValueError:
                utils.bot.reply_to(message, "Индекс должен быть больше нуля.")
                return

            try:
                who_id = whitelist[index][0]
            except IndexError:
                utils.bot.reply_to(message, "Пользователь с данным индексом не найден в вайтлисте!")
                return

            try:
                who_name = utils.username_parser_chat_member(utils.bot.get_chat_member(utils.main_chat_id, who_id),
                                                             html=True)
                if who_name == "":
                    sqlWorker.whitelist(who_id, remove=True)
                    utils.bot.reply_to(message, "Удалена некорректная запись!")
                    return
            except telebot.apihelper.ApiTelegramException:
                logging.error(traceback.format_exc())
                sqlWorker.whitelist(who_id, remove=True)
                utils.bot.reply_to(message, "Удалена некорректная запись!")
                return

            is_bot = False

        if utils.bot.get_me().id == who_id:
            utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            return

        if is_bot:
            utils.bot.reply_to(message, f"Вайтлист не работает для ботов!")
            return

        is_whitelist = sqlWorker.whitelist(who_id)

        unique_id = str(who_id) + "_whitelist"
        records = sqlWorker.msg_chk(unique_id=unique_id)
        if utils.is_voting_exists(records, message, unique_id):
            return

        if is_whitelist and utils.extract_arg(message.text, 1) == "add":
            utils.bot.reply_to(message, f"Пользователь {who_name} уже есть в вайтлисте!")
            return

        if not is_whitelist and utils.extract_arg(message.text, 1) == "remove":
            utils.bot.reply_to(message, f"Пользователя {who_name} нет в вайтлисте!")
            return

        if utils.extract_arg(message.text, 1) == "add":
            whitelist_text = f"добавление пользователя {who_name} в вайтлист"
        else:
            whitelist_text = f"удаление пользователя {who_name} из вайтлиста"

        vote_text = (f"Тема голосования: {whitelist_text}.\n"
                     f"Инициатор голосования: {utils.username_parser(message, True)}.")

        pool_constructor(unique_id, vote_text, message, "whitelist", utils.global_timer, utils.votes_need,
                         [who_id, who_name, utils.extract_arg(message.text, 1)], message.from_user.id)

        return

    whitelist = sqlWorker.whitelist_get_all()
    if not whitelist:
        utils.bot.reply_to(message, "Вайтлист данного чата пуст!")
        return

    threading.Thread(target=whitelist_building, args=(message, whitelist)).start()


def msg_remover(message, clearmsg):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Ответьте на сообщение пользователя, которое требуется удалить.")
        return

    if utils.bot.get_me().id == message.reply_to_message.from_user.id and sqlWorker.msg_chk(message.reply_to_message):
        utils.bot.reply_to(message, "Вы не можете удалить голосование до его завершения!")
        return

    unique_id = str(message.reply_to_message.message_id) + "_delmsg"

    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    silent_del, votes, timer_del, clear, warn = False, utils.votes_need_ban, utils.global_timer_ban, "", ""
    if clearmsg:
        silent_del, votes, timer_del, clear = True, utils.votes_need, utils.global_timer, "бесследно "
        warn = "\n\n<b>Внимание, голосования для бесследной очистки не закрепляются автоматически. Пожалуйста, " \
               "закрепите их самостоятельно при необходимости.</b>\n"

    vote_text = (f"Тема голосования: удаление сообщения пользователя "
                 f"{utils.username_parser(message.reply_to_message, True)}"
                 f".\nИнициатор голосования: {utils.username_parser(message, True)}." + warn)

    pool_constructor(unique_id, vote_text, message, "delete message", timer_del, votes,
                     [message.reply_to_message.message_id, utils.username_parser(message.reply_to_message), silent_del],
                     message.from_user.id, silent=silent_del)


@utils.bot.message_handler(commands=['delete'])
def delete_msg(message):
    msg_remover(message, False)


@utils.bot.message_handler(commands=['clear'])
def clear_msg(message):
    msg_remover(message, True)


@utils.bot.message_handler(commands=['op'])
def op(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        who_id, who_name, _ = utils.reply_msg_target(message)
    else:
        who_id, who_name, _ = utils.reply_msg_target(message.reply_to_message)

    if utils.bot.get_chat_member(utils.main_chat_id, who_id).status == "administrator":
        utils.bot.reply_to(message, "Пользователь уже администратор.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, who_id).status == "creator":
        utils.bot.reply_to(message, "Пользователь является создателем чата.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, who_id).status == "left" or \
            utils.bot.get_chat_member(utils.main_chat_id, who_id).status == "kicked":
        utils.bot.reply_to(message, "Пользователь не состоит в чате.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, who_id).status == "restricted":
        utils.bot.reply_to(message, "Ограниченный пользователь не может стать админом.")
        return

    unique_id = str(who_id) + "_op"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    vote_text = (f"Тема голосования: выдача прав администратора пользователю {utils.html_fix(who_name)}"
                 f".\nИнициатор голосования: {utils.username_parser(message, True)}."
                 "\n<b>Звание можно будет установить ПОСЛЕ закрытия голосования.</b>")

    pool_constructor(unique_id, vote_text, message, "op", utils.global_timer, utils.votes_need,
                     [who_id, who_name], message.from_user.id)


@utils.bot.message_handler(commands=['rank'])
def rank(message):
    if not utils.botname_checker(message):
        return

    if message.reply_to_message is None or message.reply_to_message.from_user.id == message.from_user.id:
        if utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status == "administrator":

            if utils.extract_arg(message.text, 1) is None:
                utils.bot.reply_to(message, "Звание не может быть пустым.")
                return

            rank_text = message.text.split(maxsplit=1)[1]

            if len(rank_text) > 16:
                utils.bot.reply_to(message, "Звание не может быть длиннее 16 символов.")
                return

            try:
                utils.bot.set_chat_administrator_custom_title(utils.main_chat_id, message.from_user.id, rank_text)
                utils.bot.reply_to(message, "Звание \"" + rank_text + "\" успешно установлено пользователю "
                                   + utils.username_parser(message, True) + ".")
            except telebot.apihelper.ApiTelegramException as e:
                if "ADMIN_RANK_EMOJI_NOT_ALLOWED" in str(e):
                    utils.bot.reply_to(message, "В звании не поддерживаются эмодзи.")
                    return
                logging.error(traceback.format_exc())
                utils.bot.reply_to(message, "Не удалось сменить звание.")
            return
        elif utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status == "creator":
            utils.bot.reply_to(message, "Я не могу изменить звание создателя чата.")
            return
        else:
            utils.bot.reply_to(message, "Вы не являетесь администратором.")
            return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Ответьте на сообщение бота, звание которого вы хотите сменить.")
        return

    if not message.reply_to_message.from_user.is_bot:
        utils.bot.reply_to(message, "Вы не можете менять звание других пользователей (кроме ботов).")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).status != "administrator":
        utils.bot.reply_to(message, "Данный бот не является администратором.")
        return

    if utils.bot.get_me().id == message.reply_to_message.from_user.id:
        utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return

    unique_id = str(message.reply_to_message.from_user.id) + "_rank"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    if utils.extract_arg(message.text, 1) is None:
        utils.bot.reply_to(message, "Звание не может быть пустым.")
        return

    rank_text = message.text.split(maxsplit=1)[1]

    if len(rank_text) > 16:
        utils.bot.reply_to(message, "Звание не может быть длиннее 16 символов.")
        return

    vote_text = ("Тема голосования: смена звания бота " + utils.username_parser(message.reply_to_message, True)
                 + f"на \"{utils.html_fix(rank_text)}\""
                   f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, "rank", utils.global_timer, utils.votes_need,
                     [message.reply_to_message.from_user.id, utils.username_parser(message.reply_to_message),
                      rank_text, utils.username_parser(message)], message.from_user.id)


@utils.bot.message_handler(commands=['deop'])
def deop(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if utils.extract_arg(message.text, 1) != "me" and message.reply_to_message is None:
        utils.bot.reply_to(message, "Ответьте на сообщение или используйте аргумент \"me\"")
        return

    me = True if utils.extract_arg(message.text, 1) == "me" else False
    if message.reply_to_message is not None:
        if message.reply_to_message.from_user.id == message.from_user.id:
            me = True

    if me:
        if utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status == "creator":
            utils.bot.reply_to(message, "Вы являетесь создателем чата, я не могу снять ваши права.")
            return
        if utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status != "administrator":
            utils.bot.reply_to(message, "Вы не являетесь администратором!")
            return
        try:
            utils.bot.restrict_chat_member(utils.main_chat_id, message.from_user.id,
                                           None, can_send_messages=True)
            utils.bot.restrict_chat_member(utils.main_chat_id, message.from_user.id,
                                           None, True, True, True, True, True, True, True, True)
            utils.bot.reply_to(message,
                               "Пользователь " + utils.username_parser(message) + " добровольно ушёл в отставку."
                               + "\nСпасибо за верную службу!")
            return
        except telebot.apihelper.ApiTelegramException:
            logging.error(traceback.format_exc())
            utils.bot.reply_to(message, "Я не могу изменить ваши права!")
            return

    who_id, who_name, _ = utils.reply_msg_target(message.reply_to_message)

    if utils.bot.get_chat_member(utils.main_chat_id, who_id).status == "creator":
        utils.bot.reply_to(message, f"Пользователь {who_name} является создателем чата, я не могу снять его права.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, who_id).status != "administrator":
        utils.bot.reply_to(message, f"Пользователь {who_name} не является администратором!")
        return

    if utils.bot.get_me().id == message.reply_to_message.from_user.id:
        utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return

    unique_id = str(who_id) + "_deop"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    vote_text = (f"Тема голосования: снятие прав администратора с пользователя {utils.html_fix(who_name)}"
                 f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, "deop", utils.global_timer, utils.votes_need, [who_id, who_name],
                     message.from_user.id)


@utils.bot.message_handler(commands=['title'])
def title(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if utils.extract_arg(message.text, 1) is None:
        utils.bot.reply_to(message, "Название чата не может быть пустым.")
        return

    if len(message.text.split(maxsplit=1)[1]) > 255:
        utils.bot.reply_to(message, "Название не должно быть длиннее 255 символов!")
        return

    if utils.bot.get_chat(utils.main_chat_id).title == message.text.split(maxsplit=1)[1]:
        utils.bot.reply_to(message, "Название чата не может совпадать с существующим названием!")
        return

    unique_id = "title"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    vote_text = ("От пользователя " + utils.username_parser(message, True)
                 + " поступило предложение сменить название чата на \""
                 + utils.html_fix(message.text.split(maxsplit=1)[1]) + "\".")

    pool_constructor(unique_id, vote_text, message, unique_id, utils.global_timer, utils.votes_need,
                     [message.text.split(maxsplit=1)[1], utils.username_parser(message)],
                     message.from_user.id)


@utils.bot.message_handler(commands=['description'])
def description(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is not None:
        if message.reply_to_message.text is not None:
            description_text = message.reply_to_message.text
            if len(description_text) > 255:
                utils.bot.reply_to(message, "Описание не должно быть длиннее 255 символов!")
                return

        else:
            utils.bot.reply_to(message, "В отвеченном сообщении не обнаружен текст!")
            return
    else:
        description_text = ""

    if utils.bot.get_chat(utils.main_chat_id).description == description_text:
        utils.bot.reply_to(message, "Описание чата не может совпадать с существующим описанием!")
        return

    formatted_desc = " пустое" if description_text == "" else f":\n<code>{utils.html_fix(description_text)}</code>"

    vote_text = (f"Тема голосования: смена описания чата на{formatted_desc}\n"
                 f"Инициатор голосования: {utils.username_parser(message, True)}.")

    unique_id = "desc"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    pool_constructor(unique_id, vote_text, message, "description", utils.global_timer, utils.votes_need,
                     [description_text, utils.username_parser(message)], message.from_user.id)


@utils.bot.message_handler(commands=['chatpic'])
def chat_pic(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данное голосование можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:
        utils.bot.reply_to(message, "Пожалуйста, используйте эту команду как ответ на фотографию, файл jpg или png.")
        return

    unique_id = "chatpic"
    records = sqlWorker.msg_chk(unique_id=unique_id)
    if utils.is_voting_exists(records, message, unique_id):
        return

    if message.reply_to_message.photo is not None:
        file_buffer = (utils.bot.download_file
                       (utils.bot.get_file(message.reply_to_message.photo[-1].file_id).file_path))
    elif message.reply_to_message.document is not None:
        if not message.reply_to_message.document.mime_type == "image/png" and \
                not message.reply_to_message.document.mime_type == "image/jpeg":
            utils.bot.reply_to(message, "Документ не является фотографией")
            return
        file_buffer = (utils.bot.download_file(utils.bot.get_file(message.reply_to_message.document.file_id).file_path))
    else:
        utils.bot.reply_to(message, "В сообщении не обнаружена фотография")
        return

    try:
        tmp_img = open(utils.PATH + 'tmp_img', 'wb')
        tmp_img.write(file_buffer)
    except Exception as e:
        logging.error((str(e)))
        logging.error(traceback.format_exc())
        utils.bot.reply_to(message, "Ошибка записи изображения в файл!")
        return

    vote_text = ("Тема голосования: смена аватарки чата"
                 f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

    pool_constructor(unique_id, vote_text, message, "chat picture", utils.global_timer,
                     utils.votes_need, [utils.username_parser(message)], message.from_user.id)


@utils.bot.message_handler(commands=['random', 'redrum'])
def random_msg(message):
    if not utils.botname_checker(message):
        return

    try:
        abuse_vote_timer = int(utils.vote_abuse.get("random"))
    except TypeError:
        abuse_vote_timer = 0

    abuse_random = sqlWorker.abuse_random(message.chat.id)

    if abuse_vote_timer + abuse_random > int(time.time()) or abuse_random < 0:
        return

    utils.vote_abuse.update({"random": int(time.time())})

    msg_id = ""
    for i in range(5):
        try:
            msg_id = random.randint(1, message.id)
            utils.bot.forward_message(message.chat.id, message.chat.id, msg_id)
            return
        except telebot.apihelper.ApiTelegramException:
            pass

    logging.error(traceback.format_exc())
    utils.bot.reply_to(message, "Ошибка взятия рандомного сообщения с номером {}!".format(msg_id))


@utils.bot.message_handler(commands=['reset'])
def reset(message):
    if not utils.botname_checker(message):
        return

    if utils.debug:
        sqlWorker.abuse_remove(message.chat.id)
        utils.bot.reply_to(message, "Абуз инвайта и союзников сброшен.")


@utils.bot.message_handler(commands=['getid'])
def get_id(message):
    if not utils.botname_checker(message, getchat=True):
        return

    if utils.debug:
        print(message.chat.id)
        utils.bot.reply_to(message, "ID чата сохранён")


@utils.bot.message_handler(commands=['getuser'])
def get_usr(message):
    if not utils.botname_checker(message):
        return

    if utils.debug and message.reply_to_message is not None:
        user_id, username, _ = utils.reply_msg_target(message.reply_to_message)
        utils.bot.reply_to(message, f"ID пользователя {username} - {user_id}")


@utils.bot.message_handler(commands=['help'])
def help_msg(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    try:
        help_text = open(utils.PATH + "help.txt", encoding="utf-8").read()
    except FileNotFoundError:
        utils.bot.reply_to(message, "Файл help.txt не найден")
        return
    except IOError:
        utils.bot.reply_to(message, "Файл help.txt не читается")
        return

    utils.bot.reply_to(message, help_text, parse_mode="html")


@utils.bot.message_handler(commands=['rules'])
def rules_msg(message):
    if not utils.botname_checker(message) or not utils.rules:
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    try:
        rules_text = open(utils.PATH + "rules.txt", encoding="utf-8").read()
    except FileNotFoundError:
        utils.bot.reply_to(message, "Файл rules.txt не найден")
        return
    except IOError:
        utils.bot.reply_to(message, "Файл rules.txt не читается")
        return

    utils.bot.reply_to(message, rules_text, parse_mode="html")


@utils.bot.message_handler(commands=['votes'])
def votes_msg(message):
    global functions
    if not utils.botname_checker(message):
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    records = sqlWorker.get_all_pools()
    pool_list = ""
    number = 1

    if utils.bot.get_chat(utils.main_chat_id).username is not None:
        format_chat_id = utils.bot.get_chat(utils.main_chat_id).username
    else:
        format_chat_id = "c/" + str(utils.main_chat_id)[4:]

    for record in records:
        pool_list = pool_list + f"{number}. https://t.me/{format_chat_id}/{record[1]}, " \
                                f"тип - {functions[record[2]][1]}, " + \
                    f"до завершения – {utils.formatted_timer(record[5] - int(time.time()))}\n"
        number = number + 1

    if pool_list == "":
        pool_list = "У вас нет активных голосований!"
    else:
        pool_list = "Список активных голосований:\n" + pool_list

    utils.bot.reply_to(message, pool_list)


@utils.bot.message_handler(commands=['abyss'])
def mute_user(message):
    if not utils.botname_checker(message):
        return

    if utils.abuse_mode == 0:
        utils.bot.reply_to(message, "Команда /abyss отключена в файле конфигурации бота.")
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате.")
        return

    if message.reply_to_message is None:

        if utils.abuse_mode == 2:
            only_for_admins = "\nВ текущем режиме команду могут применять только администраторы чата."
        else:
            only_for_admins = ""

        utils.bot.reply_to(message, "Ответьте на сообщение пользователя, которого необходимо отправить в мут.\n"
                           + "ВНИМАНИЕ: использовать только в крайних случаях - во избежание злоупотреблений "
                           + "вы так же будете лишены прав на тот же срок.\n"
                           + "Даже если у вас есть права админа, вы будете их автоматически лишены, "
                           + "если они были выданы с помощью бота." + only_for_admins)
        return

    if utils.bot.get_me().id == message.reply_to_message.from_user.id:
        utils.bot.reply_to(message, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        return

    if message.from_user.id != message.reply_to_message.from_user.id and utils.abuse_mode == 2:
        if utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status != "administrator" and \
                utils.bot.get_chat_member(utils.main_chat_id, message.from_user.id).status != "creator":
            utils.bot.reply_to(message, "В текущем режиме команду могут применять только администраторы чата.")
            return

    if utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).status == "restricted":
        utils.bot.reply_to(message, "Он и так в муте, не увеличивайте его страдания.")
        return

    if utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).status == "kicked" \
            or utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).status == "left":
        utils.bot.reply_to(message, "Данный пользователь не состоит в чате.")
        return

    timer_mute = 3600
    if utils.extract_arg(message.text, 1) is not None:
        timer_mute = utils.time_parser(utils.extract_arg(message.text, 1))
        if timer_mute is None:
            utils.bot.reply_to(message, "Неправильный аргумент, укажите время мута от 31 секунды до 12 часов.")
            return

    if not 30 < timer_mute <= 43200:
        utils.bot.reply_to(message, "Время не должно быть меньше 31 секунды и больше 12 часов.")
        return

    try:
        abuse_vote_timer = int(utils.vote_abuse.get("abuse" + str(message.from_user.id)))
    except TypeError:
        abuse_vote_timer = 0

    if abuse_vote_timer + 10 > int(time.time()):
        return

    utils.vote_abuse.update({"abuse" + str(message.from_user.id): int(time.time())})

    try:
        utils.bot.restrict_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id,
                                       until_date=int(time.time()) + timer_mute, can_send_messages=False,
                                       can_change_info=False, can_invite_users=False, can_pin_messages=False)
        if message.from_user.id == message.reply_to_message.from_user.id:
            if utils.rate:
                sqlWorker.update_rate(message.from_user.id, -3)
                utils.bot.reply_to(message, f"Пользователь {utils.username_parser(message)}"
                                   + f" решил отдохнуть от чата на {utils.formatted_timer(timer_mute)}"
                                   + " и снизить себе рейтинг на 3 пункта.")
            else:
                utils.bot.reply_to(message, f"Пользователь {utils.username_parser(message)}"
                                   + f" решил отдохнуть от чата на {utils.formatted_timer(timer_mute)}")
            return
        if not utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).user.is_bot \
                and utils.rate:
            sqlWorker.update_rate(message.reply_to_message.from_user.id, -5)
    except telebot.apihelper.ApiTelegramException:
        logging.error(traceback.format_exc())
        utils.bot.reply_to(message, "Я не смог снять права данного пользователя. Не имею права.")
        return

    try:
        utils.bot.restrict_chat_member(utils.main_chat_id, message.from_user.id,
                                       until_date=int(time.time()) + timer_mute, can_send_messages=False,
                                       can_change_info=False, can_invite_users=False, can_pin_messages=False)
        if not utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).user.is_bot \
                and utils.rate:
            sqlWorker.update_rate(message.from_user.id, -5)
    except telebot.apihelper.ApiTelegramException:
        logging.error(traceback.format_exc())
        utils.bot.reply_to(message, "Я смог снять права данного пользователя на "
                           + utils.formatted_timer(timer_mute) + ", но не смог снять права автора заявки.")
        return

    user_rate = ""
    if not utils.bot.get_chat_member(utils.main_chat_id, message.reply_to_message.from_user.id).user.is_bot \
            and utils.rate:
        user_rate = "\nРейтинг обоих пользователей снижен на 5 пунктов."

    utils.bot.reply_to(message, f"<b>Обоюдоострый Меч сработал</b>.\nТеперь {utils.username_parser(message, True)} "
                                f"и {utils.username_parser(message.reply_to_message, True)} "
                                f"будут дружно молчать в течении " + utils.formatted_timer(timer_mute) + user_rate,
                       parse_mode="html")


@utils.bot.message_handler(content_types=['new_chat_members'])
def whitelist_checker(message):
    def welc_msg_get():
        try:
            file = open(utils.PATH + "welcome.txt", 'r', encoding="utf-8")
            welc_msg = file.read().format(utils.username_parser_invite(message), message.chat.title)
            file.close()
        except FileNotFoundError:
            logging.warning("file \"welcome.txt\" isn't found. The standard welcome message will be used.")
            welc_msg = utils.welc_default.format(utils.username_parser_invite(message), message.chat.title)
        except (IOError, IndexError):
            logging.error("file \"welcome.txt\" isn't readable. The standard welcome message will be used.")
            logging.error(traceback.format_exc())
            welc_msg = utils.welc_default.format(utils.username_parser_invite(message), message.chat.title)
        if welc_msg == "":
            logging.warning("file \"welcome.txt\" is empty. The standard welcome message will be used.")
            welc_msg = utils.welc_default.format(utils.username_parser_invite(message), message.chat.title)
        return welc_msg

    user_id = message.json.get("new_chat_participant").get("id")

    if utils.bot.get_chat_member(utils.main_chat_id, user_id).status == "creator":
        utils.bot.reply_to(message, "Приветствую вас, Владыка.")
        return

    if not (sqlWorker.whitelist(user_id) or message.json.get("new_chat_participant").get("is_bot")):
        # Fuck you Durov
        if message.chat.id != utils.main_chat_id:
            return

        allies = sqlWorker.get_allies()
        if allies is not None:
            for i in allies:
                if utils.bot.get_chat_member(i[0], user_id).status != "left" \
                        and utils.bot.get_chat_member(i[0], user_id).status != "kicked":
                    sqlWorker.whitelist(user_id, add=True)
                    utils.bot.reply_to(message, welc_msg_get())
                    return
        try:
            utils.bot.ban_chat_member(utils.main_chat_id, user_id, until_date=int(time.time()) + 86400)
            utils.bot.reply_to(message, "Пользователя нет в вайтлисте, он заблокирован на 1 сутки.")
        except telebot.apihelper.ApiTelegramException:
            logging.error(traceback.format_exc())
            utils.bot.reply_to(message, "Ошибка блокировки вошедшего пользователя. Недостаточно прав?")
    elif not message.json.get("new_chat_participant").get("is_bot") and message.chat.id == utils.main_chat_id:
        utils.bot.reply_to(message, welc_msg_get())
    elif message.chat.id == utils.main_chat_id:
        unique_id = str(user_id) + "_new_usr"
        records = sqlWorker.msg_chk(unique_id=unique_id)
        if utils.is_voting_exists(records, message, unique_id):
            return
        try:
            utils.bot.restrict_chat_member(utils.main_chat_id, user_id, can_send_messages=False, can_change_info=False,
                                           can_invite_users=False, can_pin_messages=False,
                                           until_date=int(time.time()) + 60)
        except telebot.apihelper.ApiTelegramException:
            logging.error(traceback.format_exc())
            utils.bot.reply_to(message, "Ошибка блокировки нового бота. Недостаточно прав?")
            return

        vote_text = ("Требуется подтверждение вступления нового бота, добавленного пользователем "
                     + utils.username_parser(message, True) + ", в противном случае он будет кикнут")

        pool_constructor(unique_id, vote_text, message, "captcha", 60, utils.votes_need,
                         [utils.username_parser_invite(message), user_id, "бота"], utils.bot.get_me().id)


@utils.bot.message_handler(commands=['allies'])
def allies_list(message):
    if not utils.botname_checker(message):
        return

    if message.chat.id == message.from_user.id:
        utils.bot.reply_to(message, "Данная команда не может быть запущена в личных сообщениях.")
        return

    mode = utils.extract_arg(message.text, 1)

    if mode == "add" or mode == "remove":

        if message.chat.id == utils.main_chat_id:
            utils.bot.reply_to(message, "Данную команду нельзя запустить в основном чате!")
            return

        if sqlWorker.get_ally(message.chat.id) is not None and mode == "add":
            utils.bot.reply_to(message, "Данный чат уже входит в список союзников!")
            return

        if sqlWorker.get_ally(message.chat.id) is None and mode == "remove":
            utils.bot.reply_to(message, "Данный чат не входит в список союзников!")
            return

        abuse_chk = sqlWorker.abuse_check(message.chat.id)
        if abuse_chk > 0 and mode == "add":
            utils.bot.reply_to(message, "Сработала защита от абуза добавления в союзники! Вам следует подождать ещё "
                               + utils.formatted_timer(abuse_chk - int(time.time())))
            return

        unique_id = str(message.chat.id) + "_allies"
        records = sqlWorker.msg_chk(unique_id=unique_id)
        if utils.is_voting_exists(records, message, unique_id):
            return

        if mode == "add":
            vote_type_text, vote_type = "установка", "add allies"
            invite = utils.bot.get_chat(message.chat.id).invite_link
            if invite is None:
                invite = "\nИнвайт-ссылка на данный чат отсутствует."
            else:
                invite = f"\nИнвайт-ссылка на данный чат: {invite}."
        else:
            vote_type_text, vote_type = "разрыв", "remove allies"
            invite = ""

        vote_text = (f"Тема голосования: {vote_type_text} союзных отношений с чатом "
                     f"<b>{utils.html_fix(utils.bot.get_chat(message.chat.id).title)}</b>{invite}"
                     f".\nИнициатор голосования: {utils.username_parser(message, True)}.")

        pool_constructor(unique_id, vote_text, message, vote_type, 86400, utils.votes_need,
                         [message.chat.id], message.from_user.id, adduser=True)

        mode_text = "создании" if mode == "add" else "разрыве"

        utils.bot.reply_to(message, f"Голосование о {mode_text} союза отправлено в чат "
                                    f"<b>{utils.html_fix(utils.bot.get_chat(utils.main_chat_id).title)}</b>.\n"
                                    f"Оно завершится через 24 часа или ранее в зависимости от количества голосов.",
                           parse_mode="html")
        return

    elif mode is not None:
        utils.bot.reply_to(message, "Неправильный аргумент (поддерживаются add и remove).")
        return

    if sqlWorker.get_ally(message.chat.id) is not None:
        utils.bot.reply_to(message, "Данный чат является союзным чатом для "
                           + utils.bot.get_chat(utils.main_chat_id).title + ", ссылка для инвайта - "
                           + utils.bot.get_chat(utils.main_chat_id).invite_link)
        return

    if message.chat.id != utils.main_chat_id:
        utils.bot.reply_to(message, "Данную команду без аргументов можно запустить "
                                    "только в основном чате или в союзных чатах.")
        return

    allies_text = "Список союзных чатов: \n"
    allies = sqlWorker.get_allies()
    if allies is None:
        utils.bot.reply_to(message, "В настоящее время у вас нет союзников.")
        return

    for i in allies:
        try:
            invite = utils.bot.get_chat(i[0]).invite_link
            if invite is None:
                invite = "инвайт-ссылка отсутствует"
            allies_text = allies_text + utils.bot.get_chat(i[0]).title + " - " + invite + "\n"
        except telebot.apihelper.ApiTelegramException:
            logging.error(traceback.format_exc())

    utils.bot.reply_to(message, allies_text)


@utils.bot.message_handler(commands=['revoke'])
def revoke(message):
    if not utils.botname_checker(message):
        return

    is_allies = False if sqlWorker.get_ally(message.chat.id) is None else True

    if message.chat.id != utils.main_chat_id and not is_allies:
        utils.bot.reply_to(message, "Данную команду можно запустить только в основном чате или в союзных чатах.")
        return

    try:
        utils.bot.revoke_chat_invite_link(utils.main_chat_id, utils.bot.get_chat(utils.main_chat_id).invite_link)
        utils.bot.reply_to(message, "Пригласительная ссылка на основной чат успешно сброшена.")
    except telebot.apihelper.ApiTelegramException:
        utils.bot.reply_to(message, "Ошибка сброса основной пригласительной ссылки! Подробная информация в логах бота.")


@utils.bot.message_handler(commands=['version'])
def revoke(message):
    if not utils.botname_checker(message):
        return

    utils.bot.reply_to(message, f"Версия бота: {utils.VERSION}\nДата сборки: {utils.BUILD_DATE}\n"
                                f"Created by Allnorm aka Peter Burzec")


@utils.bot.message_handler(commands=['niko'])
def niko(message):
    if not utils.botname_checker(message):
        return

    try:
        utils.bot.send_sticker(message.chat.id,
                               random.choice(utils.bot.get_sticker_set("OneShotSolstice").stickers).file_id)
        # utils.bot.send_sticker(message.chat.id, open(os.path.join("ee", random.choice(os.listdir("ee"))), 'rb'))
        # Random file
    except (FileNotFoundError, telebot.apihelper.ApiTelegramException, IndexError):
        pass


def call_msg_chk(call_msg):
    records = sqlWorker.msg_chk(message_vote=call_msg.message)
    if not records:
        sqlWorker.rem_rec(call_msg.message.id)
        utils.bot.edit_message_text(utils.html_fix(call_msg.message.text)
                                    + "\n\n<b>Голосование не найдено в БД и закрыто.</b>",
                                    utils.main_chat_id, call_msg.message.id, parse_mode='html')
        try:
            utils.bot.unpin_chat_message(utils.main_chat_id, call_msg.message.id)
        except telebot.apihelper.ApiTelegramException:
            logging.error(traceback.format_exc())

    return records


@utils.bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_vote(call_msg):
    pool = call_msg_chk(call_msg)
    if not pool:
        return
    if pool[0][8] != call_msg.from_user.id:
        utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                        text='Вы не можете отменить чужое голосование!', show_alert=True)
        return
    utils.vote_abuse.clear()
    sqlWorker.rem_rec(call_msg.message.id, pool[0][0])
    try:
        os.remove(utils.PATH + pool[0][0])
    except IOError:
        pass
    utils.bot.edit_message_text(utils.html_fix(call_msg.message.text)
                                + "\n\n<b>Голосование было отменено автором голосования.</b>",
                                utils.main_chat_id, call_msg.message.id, parse_mode="html")
    utils.bot.reply_to(call_msg.message, "Голосование было отменено.")

    try:
        utils.bot.unpin_chat_message(utils.main_chat_id, call_msg.message.id)
    except telebot.apihelper.ApiTelegramException:
        logging.error(traceback.format_exc())


@utils.bot.callback_query_handler(func=lambda call: call.data == "vote")
def my_vote(call_msg):
    if not call_msg_chk(call_msg):
        return

    user_ch = sqlWorker.is_user_voted(call_msg.from_user.id, call_msg.message.id)
    if user_ch:
        if user_ch == "yes":
            utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                            text='Вы голосовали за вариант "да".', show_alert=True)
        elif user_ch == "no":
            utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                            text='Вы голосовали за вариант "нет".', show_alert=True)
    else:
        utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                        text='Вы не голосовали в данном опросе!', show_alert=True)


@utils.bot.callback_query_handler(func=lambda call: True)
def callback_inline(call_msg):
    if call_msg.data != "yes" and call_msg.data != "no":
        return

    def get_abuse_timer():
        try:
            abuse_vote_timer = int(utils.vote_abuse.get(str(call_msg.message.id) + "." + str(call_msg.from_user.id)))
        except TypeError:
            abuse_vote_timer = None

        if abuse_vote_timer is not None:
            if abuse_vote_timer + utils.wait_timer > int(time.time()):
                please_wait = utils.wait_timer - int(time.time()) + abuse_vote_timer
                utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                                text="Вы слишком часто нажимаете кнопку. Пожалуйста, подождите ещё "
                                                     + str(please_wait) + " секунд", show_alert=True)
                return True
            else:
                utils.vote_abuse.pop(str(call_msg.message.id) + "." + str(call_msg.from_user.id), None)
                return False

    records = call_msg_chk(call_msg)
    if not records:
        return

    if records[0][5] <= int(time.time()):
        utils.vote_abuse.clear()
        vote_result(records[0][0], call_msg.message)
        return

    unique_id = records[0][0]
    counter_yes = records[0][3]
    counter_no = records[0][4]
    votes_need_current = records[0][7]

    user_ch = sqlWorker.is_user_voted(call_msg.from_user.id, call_msg.message.id)
    if user_ch:
        if utils.vote_mode == 1:
            option = {"yes": "да", "no": "нет"}
            utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                            text=f'Вы уже голосовали за вариант "{option[user_ch]}". '
                                                 f'Смена голоса запрещена.', show_alert=True)
        elif utils.vote_mode == 2:
            if call_msg.data != user_ch:
                if get_abuse_timer():
                    return
                if call_msg.data == "yes":
                    counter_yes = counter_yes + 1
                    counter_no = counter_no - 1
                if call_msg.data == "no":
                    counter_no = counter_no + 1
                    counter_yes = counter_yes - 1
                sqlWorker.pool_update(counter_yes, counter_no, unique_id)
                sqlWorker.user_vote_update(call_msg, utils.private_checker(call_msg))
                utils.vote_update(counter_yes, counter_no, call_msg.message)
            else:
                utils.bot.answer_callback_query(callback_query_id=call_msg.id,
                                                text="Вы уже голосовали за этот вариант. " +
                                                     "Отмена голоса запрещена.", show_alert=True)
        else:
            if get_abuse_timer():
                return
            if call_msg.data != user_ch:
                if call_msg.data == "yes":
                    counter_yes = counter_yes + 1
                    counter_no = counter_no - 1
                if call_msg.data == "no":
                    counter_no = counter_no + 1
                    counter_yes = counter_yes - 1
                sqlWorker.user_vote_update(call_msg, utils.private_checker(call_msg))
            else:
                if call_msg.data == "yes":
                    counter_yes = counter_yes - 1
                else:
                    counter_no = counter_no - 1
                sqlWorker.user_vote_remove(call_msg)
            sqlWorker.pool_update(counter_yes, counter_no, unique_id)
            utils.vote_update(counter_yes, counter_no, call_msg.message)
    else:
        if call_msg.data == "yes":
            counter_yes = counter_yes + 1
        if call_msg.data == "no":
            counter_no = counter_no + 1

        sqlWorker.pool_update(counter_yes, counter_no, unique_id)
        sqlWorker.user_vote_update(call_msg, utils.private_checker(call_msg))
        utils.vote_update(counter_yes, counter_no, call_msg.message)

    if counter_yes >= votes_need_current or counter_no >= votes_need_current:
        utils.vote_abuse.clear()
        vote_result(unique_id, call_msg.message)
        return

    utils.vote_abuse.update({str(call_msg.message.id) + "." + str(call_msg.from_user.id): int(time.time())})


utils.bot.infinity_polling()
