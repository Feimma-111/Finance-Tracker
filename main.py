import json
import os

file_exists = os.path.exists('information_save_file')
if file_exists:
    with open('information_save_file', 'r') as f:
else :
    with open('information_save_file', 'w') as f:
        # initialize information
print("Hello and this is the start of my finance tracker")
run = True
total_transactions = []
while run :
    action = input("If you would like to enter a new transaction, press t" \
           " if you would like to see your portfolio, press p, to end the program, press n: ")
    if action.lower() == "t" :
        transaction = input("Please enter what your transaction was: ")
        amount = input("Please enter the amount of the transaction: ")
        category = input("Please enter the category of spending: ")
        transaction_date = input("Please enter the date of transaction: ")
        num_amount = float(amount)
        current_transaction = dict(name=transaction, price=num_amount, type=category, date=transaction_date)
        total_transactions.append(current_transaction)
    elif action.lower() == "p" :
        total_spent = 0
        for item in total_transactions:
            total_spent += item.get("price")
        print(total_spent)
    else :
        run = False


