<!-- Improved compatibility of back to top link: See: https://github.com/BenjaminWalkerBond/auto_grocier/pull/73 -->
<a name="readme-top"></a>
<!--
*** Thanks for checking out the Best-README-Template. If you have a suggestion
*** that would make this better, please fork the repo and create a pull request
*** or simply open an issue with the tag "enhancement".
*** Don't forget to give the project a star!
*** Thanks again! Now go create something AMAZING! :D
-->



<!-- PROJECT SHIELDS -->
<!--
*** I'm using markdown "reference style" links for readability.
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of the reference variables
*** for contributors-url, forks-url, etc. This is an optional, concise syntax you may use.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]



<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/BenjaminWalkerBond/auto_grocier">
    <img src="images/logo.png" alt="Logo" width="80" height="80">
  </a>

  <h3 align="center">Best-README-Template</h3>

  <p align="center">
    An awesome README template to jumpstart your projects!
    <br />
    <a href="https://github.com/BenjaminWalkerBond/auto_grocier"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/BenjaminWalkerBond/auto_grocier">View Demo</a>
    ·
    <a href="https://github.com/BenjaminWalkerBond/auto_grocier/issues">Report Bug</a>
    ·
    <a href="https://github.com/BenjaminWalkerBond/auto_grocier/issues">Request Feature</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

This project aims to consume any url from the web, get the ingredients from that webpage using chatgpt, 
and automatically place an order to H-E-B for all ingredients. It was built to help with my girlfriend's dietary restrictions (severe tree nut allergy) which makes
eating out a difficult process. Furthermore, it helps solves the problem of meal service cross contamination by making you your own meal service. The project has a tagging function that tags all ingredients. In the future, it will omit any recipes that contain tree nuts before placing an order.

[![Product Name Screen Shot][product-screenshot]](https://example.com)




<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

Selenium
BeautifulSoup4
OpenAI



<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

To get a local copy up and running follow these simple example steps.

### Prerequisites

1. Install pipenv
2. Install pyenv

**Note:** Use pipenv lock -r > requirements.txt to generate requirements file.

# Get OpenAI API key
Get an API Key at [https://platform.openai.com/account/api-keys](https://platform.openai.com/account/api-keys)

# Install Python 
[https://www.python.org/downloads/](https://www.python.org/downloads/)


### Installation

_Below is an example of how you can instruct your audience on installing and setting up your app. This template doesn't rely on any external dependencies or services._


1. Clone the repo
   ```sh
   git clone https://github.com/BenjaminWalkerBond/auto_grocier.git
   ```
2. Install python packages
   ```sh
   pipenv install
   ```
3. Enter your HEB login credentials on line 1 and 2 and your API organization id and key on line 3 and 4 of `config.txt`
   ```js
   username
   password
   org_key
   api_key
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

### Running
```sh
pipenv shell
python main.py
```

Use this space to show useful examples of how a project can be used. Additional screenshots, code examples and demos work well in this space. You may also link to more resources.

<!-- _For more examples, please refer to the [Documentation](https://example.com)_ -->

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ROADMAP -->
## Roadmap

- [ ] Add Ability to checkout
- [ ] Add Examples
- [X] Refactor project structure to use pipenv and pyenv
- [ ] Find alternative to static references to css selectors (Something like Browse AI)
- [ ] Improve chatgpt ingredient accuracy
- [ ] Move to local chatgpt4 implementation for cost saving ( maybe [this tutorial](https://www.pcguide.com/apps/can-chatgpt-run-locally/) )
- [ ] Move package management to poetry
- [ ] Enhance login to automatically grab verification code from email if sent
- [ ] Add hit rate (ingredients found in text versus tagged)
- [ ] Add recipe storage ( dynamodb? )
- [ ] Add recipe class

See the [open issues](https://github.com/BenjaminWalkerBond/auto_grocier/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE.txt` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Benjamin Bond - [https://benjaminwalkerbond.com/contact](https://benjaminwalkerbond.com/contact)

Project Link: [https://github.com/BenjaminWalkerBond/auto_grocier](https://github.com/BenjaminWalkerBond/auto_grocier)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

Use this space to list resources you find helpful and would like to give credit to. I've included a few of my favorites to kick things off!

* [Choose an Open Source License](https://choosealicense.com)
* [GitHub Emoji Cheat Sheet](https://www.webpagefx.com/tools/emoji-cheat-sheet)
* [GitHub Pages](https://pages.github.com)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/BenjaminWalkerBond/auto_grocier.svg?style=for-the-badge
[contributors-url]: https://github.com/BenjaminWalkerBond/auto_grocier/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/BenjaminWalkerBond/auto_grocier.svg?style=for-the-badge
[forks-url]: https://github.com/BenjaminWalkerBond/auto_grocier/network/members
[stars-shield]: https://img.shields.io/github/stars/BenjaminWalkerBond/auto_grocier.svg?style=for-the-badge
[stars-url]: https://github.com/BenjaminWalkerBond/auto_grocier/stargazers
[issues-shield]: https://img.shields.io/github/issues/BenjaminWalkerBond/auto_grocier.svg?style=for-the-badge
[issues-url]: https://github.com/BenjaminWalkerBond/auto_grocier/issues
[license-shield]: https://img.shields.io/github/license/BenjaminWalkerBond/auto_grocier.svg?style=for-the-badge
[license-url]: https://github.com/BenjaminWalkerBond/auto_grocier/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/othneildrew
[product-screenshot]: images/screenshot.png
[chatgpt-url]: https://openai.com/blog/chatgpt
