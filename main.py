import json
import os
import datetime
from collections import defaultdict

print("Hello and welcome to my finance tracker")
run = True
total_transactions = []
file_exists = os.path.exists('information_save_file')
if file_exists:
    with open('information_save_file', 'r') as f:
        for line in f:
            saved_transaction = json.loads(line)
            total_transactions.append(saved_transaction)

while run :
    action = input("Enter [p] if you would like to see your portfolio, enter [t] if you would " \
           "like to enter a new transaction, enter [s] to save your current portfolio, and " \
           "enter [n] to end the program: ")
    if action.lower() == "t" :
        transaction = input("Please enter what your transaction was: ")
        amount = input("Please enter the amount of the transaction: ")
        category = input("Please enter the category of spending: ")
        transaction_date = input("Please enter the date of transaction in the format YYYY/MM/DD: ")
        date_format = '%Y/%m/%d'
        true_date = datetime.datetime.strptime(transaction_date, date_format)
        num_amount = float(amount)
        current_transaction = dict(name=transaction, price=num_amount, type=category, date=true_date.isoformat())
        total_transactions.append(current_transaction)
    elif action.lower() == "p" :
        total_spent = 0
        section_transactions = defaultdict(float)
        for item in total_transactions:
            section_transactions[item.get("type")] += item.get("price")
            total_spent += item.get("price")
        print("This is the total you have spent: " + str(total_spent))
        print("These are the individual categories of spending: ")
        for category in section_transactions: 
            print(category + ": " + str(section_transactions[category]))

    elif action.lower() == "s" :
        with open('information_save_file', 'w') as f:
            for transaction in total_transactions: 
                json_str = json.dumps(transaction) + "\n"
                f.write(json_str)
    else :
        run = False


