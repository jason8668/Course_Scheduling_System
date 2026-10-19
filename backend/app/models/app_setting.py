"""全域系统设置(M4-3)。

不隶属任何学期的单校设置,以 key/value 存放(同 constraint_config 的理由:
加一个设置不该要一次迁移)。目前只放 SMTP 寄信设置;日后备份排程、校名等亦可入此。
密码类栏位存明文——单校自架、DB 仅校内存取;真正的隔离靠部署环境,不在应用层加密。
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), default="")
