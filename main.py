#
# File:         main.py
# Author:       Tan Duc Mai
# Email:        tan.duc.work@gmail.com
# Date:         20-Aug-21
# Description:  The main working area of the dictionary.
#   I hereby declare that I completed this work without any improper help
#   from a third party and without using any aids other than those cited.
#


# ------------------------------- Module Imports ------------------------------
"""
The time module has the sleep() function which is used to give a short break
(0.5 to 1 second) between each major part of the program.

The urllib.request module has the function which retrieves the content
of a URL directly into a local location on disk.
It is installed by default with Python 3.10 which I am using.

The requests module allows for the exchange of HTTP requests.
It requires pre-installation –> pip install requests

The bs4 module has the BeautifulSoup() function which downloads data of HTML
files from the website.
It requires pre-installation –> pip install bs4

The pygame.mixer is a module which loads and plays sound or the mp3 file.
This is what I use to play the pronunciation file downloaded by using the
urlretrieve() function.
It also requires pre-installation –> pip install pygame

The functions module contains a set of three functions, which help with code
legibility and code reuse.
"""
# Standard library imports.
from time import sleep as take_a_break
from urllib.request import urlretrieve

# Related third party imports.
import requests
from bs4 import BeautifulSoup as bs
from pygame import mixer

# Local application/library specific imports.
import functions as func


# ------------------------------- Main Function -------------------------------
def main():
    # Welcome message
    func.draw_a_line()
    print('Welcome to the Dictionary of Merriam-Webster')
    func.draw_a_line()

    # Top Lookup Right Now.
    url = f'https://www.merriam-webster.com/dictionary'
    res = requests.get(url)
    text = res.text
    soup = bs(res.content, 'html.parser')

    day = soup.find('a', attrs={'href': '/word-of-the-day'})
    for i in range(3):
        day = day.find_next('a', attrs={'href': '/word-of-the-day'})
    print('Top Lookup Right Now:', day.get_text())

    # Look up a word.
    func.draw_a_line()
    word = None
    while word is None or word == '':
        word = input('Search for a Word: ')
        if word == '':
            print('Please Enter a non-empty word.', end='\n\n')

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
        url = f'https://www.merriam-webster.com/dictionary/{word}'
        res = requests.get(url)
        text = res.text
        soup = bs(res.content, 'html.parser')

    # Now we have a valid word.
    func.draw_a_line()

    # Get the definition.
    # Count the number of definitions of the word.
    count = text.count('dtText')

    print(f'-> Definition of {word.upper()}:', end='\n\n')

    if count == 1:                  # If the word has only 1 definition
        definition = soup.find('span', class_='dtText')
        print(definition.get_text())
    else:                           # If the word has more than 1 definition
        definition = soup.find('span', class_='dtText')
        print('Entry 1 of ', count, definition.get_text(), sep='')
        func.find_all_definitions(count, definition)

    take_a_break(1)

    # Thesaurus.
    func.draw_a_line()

    try:
        # Retrieve Thesaurus webpage.
        url_1 = f'https://www.merriam-webster.com/thesaurus/{word}'
        res_1 = requests.get(url_1)
        soup_1 = bs(res_1.content, 'html.parser')

        # Synonyms.
        input('Press Enter to look up synonyms.')
        print()
        print(f'-> Synonyms of {word.upper()}: ', end='')
        synonym = soup_1.find('ul', class_='mw-list')
        print(synonym.get_text())
        take_a_break(1)

        # Related words.
        func.draw_a_line()
        input('Press Enter to look up related words.')
        print()
        print(f'-> Words related to {word.upper()}: ', end='')
        related = synonym.find_next('ul')
        print(related.get_text())
    except BaseException:
        print(f'\n\nSorry! There isn\'t a synonym for "{word}".')

    take_a_break(1)

    # MP3: the pronunciation file.
    func.draw_a_line()

    try:
        # Call the function to return the list of the elements of the URL of
        # the mp3 file for pronouncing.
        URL = func.mp3(text)

        # Convert the mp3_url from a list into a string.
        mp3_url = ''.join(URL)

        # Ask the user whether they want to hear the pronunciation.
        acceptable_response = ('Y', 'y', 'N', 'n')
        pronounce = None
        while pronounce is None or pronounce not in acceptable_response:
            pronounce = input('Do you want to hear its pronunciation? [Y/n] ')
            if pronounce not in acceptable_response:
                print('Please Enter an appropriate command.', end='\n\n')

        # Download the mp3 file to the local directory.
        urlretrieve(mp3_url, 'word_to_pronounce.mp3')

        # Repeatedly pronounce the word if user reponds 'y'.
        while pronounce.lower() == 'y':
            mixer.init()
            mixer.music.load('word_to_pronounce.mp3')
            mixer.music.play()
            # Ask the user again.
            pronounce = None
            while pronounce is None or pronounce not in acceptable_response:
                pronounce = input('One more time? [Y/n] ')
                if pronounce not in acceptable_response:
                    print('Please Enter an appropriate command.', end='\n\n')
    except ValueError:
        print(
            f'Sorry! There isn\'t a pre-recorded pronunciation for "{word}".'
        )

    take_a_break(1)

    # Close the program.
    func.draw_a_line()
    print('Thank you for using our translation service!')
    func.draw_a_line()


# --------------------------- Call the Main Function --------------------------
if __name__ == '__main__':
    main()
