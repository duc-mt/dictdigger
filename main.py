#!/usr/bin/python3

#
# File:         main.py
# Author:       Tan Duc Mai
# Email:        tan.duc.work@gmail.com
# Date:         20-Aug-21
# Description:  The main working area of the dictionary.
#   I hereby declare that I completed this work without any improper help
#   from a third party and without using any aids other than those cited.
#

"""
The predefined_procedures module contains a set of three functions which help with code legibility and code reuse.

The time module has the sleep() function which gives a short break (0.5 to 1 second) between each major part of the program.

The requests nodule allows for the exchange of HTTP requests.

The urllib.request has the urlretrieve() function which retrieves the content of a URL directly into a local location on disk.

The bs4 module has the BeautifulSoup() function which downloads data of HTML files of the website.
It requires pre-installation –> pip install bs4.

The pygame.mixer is a module which loads and plays sound or the mp3 file.
This is what I use to play the pronunciation file downloaded by using the urlretrieve() function.
It also requires pre-installation –> pip install pygame.
"""

import predefined_procedures as func
import time
import requests
import urllib.request
from bs4 import BeautifulSoup as bs
from pygame import mixer


# Welcome message.
time.sleep(1)
func.line()
print('Welcome to the Dictionary of Merriam-Webster:')
time.sleep(1)
func.line()


# Top Lookup Right Now.
url = f'https://www.merriam-webster.com/dictionary'
res = requests.get(url)
text = res.text
soup = bs(res.content, 'html.parser')

day = soup.find('a', attrs = {'href': '/word-of-the-day'})
for i in range(3):
    day = day.find_next('a', attrs = {'href': '/word-of-the-day'})
print('Top Lookup Right Now:', day.get_text())
time.sleep(1)


# Look up a Word.
func.line()
word = input('Search for a Word: ')
func.line()


# Connect to the dictionary.
url = f'https://www.merriam-webster.com/dictionary/{word}'
res = requests.get(url)
text = res.text
soup = bs(res.content, 'html.parser')


# Validate word that is not in the dictionary.
false_message = 'isn\'t in the dictionary'
while false_message in text:
    print(f'The word you\'ve entered, \'{word}\', {false_message}.\n')
    word = input('Try again: ')
    func.line()
    url = f'https://www.merriam-webster.com/dictionary/{word}'
    res = requests.get(url)
    text = res.text
    soup = bs(res.content, 'html.parser')


# Now we have a valid word.

# Get the definition.
count = text.count('dtText')        # Count the number of definitions of the word.

print(f'Definition of {word.upper()}:\n')

if count == 1:                      # If the word has only 1 definition.
    definition = soup.find('span', class_='dtText')
    print(definition.get_text())
else:                               # If the word has more than 1 definition.
    definition = soup.find('span', class_='dtText')
    print('Entry 1 of ', count, definition.get_text(), sep = '')
    func.find_all_definitions(count, definition)

time.sleep(2)


# Thesaurus.
try:
    # Retrieve Thesaurus webpage.
    url_1 = f'https://www.merriam-webster.com/thesaurus/{word}'
    res_1 = requests.get(url_1)
    soup_1 = bs(res_1.content, 'html.parser')

    # Synonyms.
    func.line()
    print(f'Synonyms of {word.upper()}: ', end = '')
    synonym = soup_1.find('ul', class_='mw-list')
    print(synonym.get_text())
    time.sleep(2)

    # Related words.
    func.line()
    print(f'Words Related to {word.upper()}: ', end = '')
    related = synonym.find_next('ul')
    print(related.get_text())
    time.sleep(2)
except:
    print(f'\nSorry! There isn\'t any synonym for "{word}".')
    time.sleep(1)


#MP3: pronunciation file.
func.line()

try:
    # Call the fucntion to return the list of the elements of the URL of the mp3 file for pronouncing.
    URL = func.mp3(text)

    # Convert the mp3_url from list into string.
    mp3_url = ''.join(URL)

    # Ask the user whether they want to hear the pronunciation.
    pronounce = input('Do you want to hear its pronunciation? (Y/N): ')
    file_name = urllib.request.urlretrieve(mp3_url, 'word_pronounce.mp3')
    while pronounce.upper() == 'Y':   
        mixer.init()
        mixer.music.load('word_pronounce.mp3')
        mixer.music.play()
        pronounce = input('One more time? (Y/N): ')
except:
    print(f'Sorry! There isn\'t any pre-recorded pronunciation for "{word}".')

time.sleep(1)


# The end.
func.line()
print('Thank you for using our translation service!')
func.line()
