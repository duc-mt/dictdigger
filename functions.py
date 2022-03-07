#
# File:         functions.py
# Author:       Tan Duc Mai
# Email:        tan.duc.work@gmail.com
# Date:         20-Aug-21
# Description:  Define resuable functions that help with code legibility.
#   I hereby declare that I completed this work without any improper help
#   from a third party and without using any aids other than those cited.
#


# ------------------------------- Module Imports ------------------------------
"""
The time module has the sleep() function which is used to give a short break
(0.5 to 1 second) between each major part of the program.

The requests module allows for the exchange of HTTP requests.
"""
# Standard library imports.
from time import sleep as take_a_break

# Related third party imports.
import requests


# ---------------------------- Function Definitions ---------------------------
def draw_line():
    # A function to draw a line break.
    print('\n-----------------------------------------------------------------------\n')
    take_a_break(1)


def find_all_definitions(count, definition):
    # A function to find all other definitions of a word.
    for i in range(2, count + 1):
        print(f'Entry {i} of {count}', end='')
        if i == 2:
            i = definition.find_next('span', class_='dtText')
        else:
            i = j.find_next('span', class_='dtText')
        j = i
        if ': ' not in i.get_text():
            print(': ', end='')
        print(i.get_text())


def mp3(text):
    # A function to pronounce the word.
    # It returns the URL of the mp3 file.
    locate = text.find('contentURL')
    mp3_url = []
    for i in text[locate + 14:]:
        if i == '"':
            return mp3_url
        else:
            mp3_url.append(i)
