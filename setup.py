from setuptools import setup

setup(
    name='beets-youtube',
    version='0.1',
    description='beets plugin to use YouTube for metadata',
    long_description=open('README.md').read(),
    author='Alok Saboo',
    author_email='',
    url='https://github.com/arsaboo/beets-jiosaavn',
    license='MIT',
    platforms='ALL',
    packages=['beetsplug'],
    install_requires=[
        'beets>=1.6.0,<3.0.0',
        'ytmusicapi>=1.10.2',
        'requests',
        'pillow',
    ],
)
