import os
import ast
import json
import telebot
import datetime
import datefinder
import pygsheets
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

# Telebot API ==================================================================

TOKEN = ''
with open('/token.json') as f:
  TOKEN = json.load(f)["TOKEN"]
bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)
URL = 'https://voidrobot.herokuapp.com/'

# Google Sheets API ==================================================================

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('client_secret.json', scope)
client = pygsheets.authorize(service_file='client_secret.json')
gsheet = client.open("Mahjong Bot Data").sheet1

#=====================================================================================

def get_name(first, last):
    if (first == None) and (last != None):
        return " " + last
    elif (first != None) and (last == None):
        return " " + first
    elif (first == None) and (last == None):
        return ""
    else:
        return " " + first + " " + last

@bot.message_handler(commands=['start'])
def send_welcome(message):
    fullname = get_name(message.from_user.first_name, message.from_user.last_name)
    bot.send_message(message.chat.id, "Hello " + fullname + "!\nType /split to try out the bill splitting function.")

@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message, "HELP!")

### ========== MAHJONG TRACKER ========== ###

mj_step = {}
def get_mj_step(chat_id):
    if chat_id in mj_step:
        return mj_step[chat_id]['step']
    else:
        mj_step[chat_id]['step'] = 0
        return 0

@bot.message_handler(content_types=['text'])
def read_input(message):
    try:
        chat_id = message.chat.id
        content = ast.literal_eval(gsheet.get_value('A1'))
        user_record = content[chat_id] if chat_id in content else []
        input_lines = message.text.split('\n')
        for line in input_lines:
            dates = datefinder.find_dates(line)
            input_date = datetime.datetime.now()
            if len(dates) > 1:
                raise ValueError("More than 1 date detected on a single line")
            elif len(dates) == 0:
                input_date = dates[0]
            
            input_amount = int(line.split(" ")[-1].replace('$', ''))
            entry = { "datetime": input_date, "amount": input_amount }
            user_record.append(entry)
        user_record = sorted(user_record, key=lambda x: x["datetime"])
        content[chat_id] = user_record
        gsheet.update_values('A1', [[str(content)]])
        bot.reply_to(message, "Done")
    except ValueError as ve:
        bot.reply_to(message, ve)
    except:
        bot.reply_to(message, "Invalid input!")

@bot.message_handler(func=lambda message: get_mj_step(message.chat.id) == 0, commands=['delete'])
def delete_step_0(message):
    try:
        chat_id = message.chat.id
        content = ast.literal_eval(gsheet.get_value('A1'))
        user_record = content[chat_id] if chat_id in content else []
        if len(user_record) == 0:
            bot.send_message(chat_id, "Sorry, you don't have any mahjong records")
        else:
            records = '*Mahjong Records*\n'
            for index in range(len(user_record)):
                dt = user_record[index]["datetime"]
                a = user_record[index]["amount"]
                amount = "$" + str(a) if a >= 0 else "-$" + str(-1 * a)
                records += str(index) + ". " + dt.strftime("%d %b %Y") + " " + amount + "\n"
            bot.send_message(chat_id, records, parse_mode='Markdown')
            mj_step[chat_id]['step'] = 1
            mj_step[chat_id]['records'] = user_record
    except:
        bot.reply_to(message, "An error occured with this input.")

@bot.message_handler(func=lambda message: get_mj_step(message.chat.id) == 1, content_types=['text'])
def delete_step_1(message):
    try:
        chat_id = message.chat.id
        user_record = mj_step[chat_id]['records']
        if not isinstance(message.text, int):
            raise TypeError()
        elif int(message.text) > len(user_record) + 1 or int(message.text) <= 0:
            raise ValueError()
        else:
            user_record.pop(int(message.text) - 1)
            content = ast.literal_eval(gsheet.get_value('A1'))
            content[chat_id] = user_record
            gsheet.update_values('A1', [[str(content)]])
            mj_step[chat_id]["step"] = 0
            bot.send_message(chat_id, "Entry successfully deleted")
    except TypeError:
        bot.reply_to(message, "That is not a number")
    except ValueError:
        bot.reply_to(message, "That number is out of bounds")
    except:
        bot.reply_to(message, "An error occured with this input")

@bot.message_handler(commands=['/stats'])
def get_statistics(message):
    try:
        chat_id = message.chat.id
        user_record = mj_step[chat_id]['records']
        if len(user_record) == 0:
            bot.send_message("Your records is empty")
            bot.send_message("Start by adding one now!")
        else:
            records = '*Mahjong Records*\n'
            for index in range(len(user_record)):
                dt = user_record[index]["datetime"]
                a = user_record[index]["amount"]
                amount = "$" + str(a) if a >= 0 else "-$" + str(-1 * a)
                records += str(index) + ". " + dt.strftime("%d %b %Y") + " " + amount + "\n" 
            bot.send_message(chat_id, records, parse_mode='Markdown')
    except:
        bot.reply_to(message, "An error occured with this input")

### ========== BILL SPLITTER ========== ###

user_db = {}

def get_step(chat_id):
    if chat_id in user_db:
        return user_db[chat_id]["step"]
    else:
        user_db[chat_id] = {}
        user_db[chat_id]["step"] = 0
        return 0

def display_names(names):
    text = 'These are the names you have entered and their corresponding *label number*:'
    for i in range(len(names)):
        text += '\n'
        text += str(i+1) + '. ' + names[i]
    return text

def calculate_bill(details, names, gst):
    db = []
    for n in names:
        data = {"name": n, "dish": [], "amount": 0}
        db.append(data)

    for line in details:
        x = line.rpartition(' $')
        price = float(x[2])
        y = x[0].split(' ', 1)
        dish = y[1]
        z = y[0].split(',')
        if (z[0].lower() == 'all'):
            z = list(range(len(names)))
        price = price / len(z) * gst
        for i in z:
            index = int(i) - 1
            db[index]["dish"].append(dish)
            db[index]["amount"] += price

    text = '*Bill Overview*\n'
    total_amount = 0
    for d in db:
        name = d["name"]
        amount = "{0:.2f}".format(d["amount"])
        total_amount += d["amount"]
        dishes = ', '.join(d["dish"])
        text += '\n' + name + ': *$' + str(amount) + '* (_' + dishes + '_)'

    text += '\n\nTotal Bill: *$' + "{0:.2f}".format(total_amount) + '*'
    return text

@bot.message_handler(func=lambda message: get_step(message.chat.id) == 0, commands=['split'])
def new_bill(message):
    bot.send_message(message.chat.id, "You have activated the bill splitter function.")
    bot.send_message(message.chat.id, "Please key in everyone's name separated by a new line.\nType 'cancel' anytime to exit this function.")
    user_db[message.chat.id]["step"] = 1

@bot.message_handler(func=lambda message: get_step(message.chat.id) == 1, content_types=['text'])
def get_names(message):
    chat_id = message.chat.id
    if (message.text.lower() == 'cancel'):
        user_db[chat_id]["step"] = 0
        bot.send_message(chat_id, "You have successfully exited the function.")
    else:
        try:
            names = message.text.splitlines()
            show_names = display_names(names)
            bot.send_message(chat_id, show_names, parse_mode='Markdown')
            
            text = 'Now enter the *label number* followed by *food item* followed by *price*.'
            text += '\nFor shared items, separate the label numbers by a *comma without spaces*.'
            text += '\nFor items shared by everyone, you can type \'all\' for the label number.'
            text += '\nType /example for detailed assistance.'
            bot.send_message(chat_id, text, parse_mode='Markdown')

            user_db[chat_id]["names"] = names
            user_db[chat_id]["step"] = 2
        except:
            bot.send_message(chat_id, 'Invalid input. Please enter names again.')

@bot.message_handler(commands=['example'])
def example_input(message):
    if (get_step(message.chat.id) == 2):
        names = user_db[message.chat.id]["names"]
        text = '*-- Scenario 1 --*\n' + names[0] + ' (Person No. 1) has ordered Fish and Chips for $7.90'
        text += '\n*Input 1:*\n`1 Fish and Chips $7.9`'
        if (len(names) >= 3):
            text += '\n\n*-- Scenario 2 --*\n' + names[1] + ' (No. 2) and ' + names[2] + ' (No. 3) shared Truffle Fries for $5.90'
        else:
            text += '\n\n*-- Scenario 2 --*\nPerson 2 and 3 shared Truffle Fries for $5.90'
        text += '\n*Input 2:*\n`2,3 Truffle Fries $5.9`'
        text += '\n\n*-- Scenario 3 --*\nEveryone shared a Beer Tower for $35'
        text += '\n*Input 3:*\n`All Beer Tower $35`'
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: get_step(message.chat.id) == 2, content_types=['text'])
def get_food(message):
    chat_id = message.chat.id
    if (message.text.lower() == 'cancel'):
        user_db[chat_id]["step"] = 0
        bot.send_message(chat_id, 'You have successfully exited the function.')
    else:
        try:
            bill_details = message.text.splitlines()
            user_db[chat_id]["details"] = bill_details
            text = calculate_bill(bill_details, user_db[chat_id]["names"], 1)
            bot.send_message(chat_id, text, parse_mode='Markdown')

            end_message = 'Type /gst1 to calculate with 7% GST\nType /gst2 to calculate with 10% service charge + 7% GST\nType /done to exit this function'
            bot.send_message(chat_id, end_message)
            user_db[chat_id]["step"] = 3
        except:
            bot.send_message(chat_id, 'Invalid input. Please enter bill details again.')

@bot.message_handler(func=lambda message: get_step(message.chat.id) == 3, commands=['gst1'])
def gst1(message):
    chat_id = message.chat.id
    details = user_db[chat_id]["details"]
    names = user_db[chat_id]["names"]
    text = calculate_bill(details, names, 1.07)
    bot.send_message(chat_id, text, parse_mode='Markdown')

    end_message = 'Type /gst2 to calculate with 10% service charge + 7% GST\nType /done to exit this function'
    bot.send_message(chat_id, end_message)

@bot.message_handler(func=lambda message: get_step(message.chat.id) == 3, commands=['gst2'])
def gst2(message):
    chat_id = message.chat.id
    details = user_db[chat_id]["details"]
    names = user_db[chat_id]["names"]
    text = calculate_bill(details, names, 1.177)
    bot.send_message(chat_id, text, parse_mode='Markdown')

    end_message = 'Type /gst1 to calculate with 7% GST\nType /done to exit this function'
    bot.send_message(chat_id, end_message)

@bot.message_handler(func=lambda message: get_step(message.chat.id) == 3, commands=['done'])
def is_done(message):
    chat_id = message.chat.id
    user_db[chat_id]["step"] = 0
    bot.send_message(chat_id, "Thank you for using this service")

### ========== WEBHOOK ========== ###

@server.route('/' + TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url = URL + TOKEN)
    return "!", 200


if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.environ.get('PORT', 18338)))