#
# File:         functions.py
# Author:       Tan Duc Mai
# Email:        tan.duc.work@gmail.com
# Date:         20-Aug-21
# Description:  Define reusable functions to improve code legibility.
#   I hereby declare that I completed this work without any improper help
#   from a third party and without using any aids other than those cited.
#


# ------------------------------- Module Imports ------------------------------
"""Description of all imported modules.

The time module has the sleep() function which is used to give a short break
(0.5 to 1 second) between each major part of the program.
"""
from time import sleep as take_a_break


# ---------------------------- Function Definitions ---------------------------
def draw_a_line():
    """Draw a line break."""
    print('\n', '-' * 71, '\n')
    take_a_break(1)


def find_all_definitions(count, definition):
    """Find all other definitions of a word."""
    word = None
    for i in range(2, count + 1):
        print(f'Entry {i}', end='')
        if i == 2:
            i = definition.find_next('span', class_='dtText')
        else:
            i = word.find_next('span', class_='dtText')
        word = i
        if ': ' not in i.get_text():
            print(': ', end='')
        print(i.get_text())


def mp3(text):
    """Pronounce the word - returns the URL of the mp3 file."""
    locate = text.find('contentURL')
    mp3_url = []
    for i in text[locate + 14:]:
        if i == '"':
            return mp3_url
        mp3_url.append(i)
    return True
