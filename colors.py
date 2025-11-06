class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAG = "\033[95m"

    @staticmethod
    def success(msg: str) -> str:
        """Сообщение об успехе"""
        return f"{Colors.GREEN}Success: {Colors.RESET} {msg}"

    @staticmethod
    def info(msg: str) -> str:
        """Информационное сообщение"""
        return f"{Colors.CYAN}Info: {Colors.RESET} {msg}"

    @staticmethod
    def error(msg: str) -> str:
        """Сообщение об ошибке"""
        return f"{Colors.RED}Error: {Colors.RESET} {msg}"

    @staticmethod
    def warning(msg: str) -> str:
        """Предупреждение"""
        return f"{Colors.YELLOW}Warning: {Colors.RESET} {msg}"

    @staticmethod
    def chapter(num: int) -> str:
        """Форматированный номер главы"""
        return f"{Colors.BOLD}{Colors.MAG}Chapter {num}{Colors.RESET}"

    @staticmethod
    def title(text: str) -> str:
        """Форматированный заголовок"""
        return f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}"