from setuptools import setup

setup(
    name='beets-jiosaavn',
    version='0.1',
    description='beets plugin to use JioSaavn for metadata',
    long_description=open('README.md').read(),
    author='Alok Saboo',
    author_email='',
    url='https://github.com/arsaboo/beets-jiosaavn',
    license='MIT',
    platforms='ALL',
    packages=['beetsplug'],
    install_requires=[
        'beets>=1.6.0',
        'MusicAPy @ git+https://github.com/dmdhrumilmistry/MusicAPy',
        'requests',
        'pillow',
    ],
)
