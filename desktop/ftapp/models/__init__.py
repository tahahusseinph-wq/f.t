"""كل جداول قاعدة البيانات."""
from ftapp.models.base import Base
from ftapp.models.auth import DeviceSession, User
from ftapp.models.catalog import (Category, CustomField, PriceHistory, PriceTier, Product,
                                  ProductFieldValue, ProductImage, ProductTierPrice, Promotion, Supplier)
from ftapp.models.finance import (CashMovement, Currency, CurrencyExchange, Employee, EmployeeTransaction,
                                  ExchangeRateHistory, Expense, ExpenseCategory, Shift)
from ftapp.models.inventory import (Batch, PurchaseInvoice, PurchaseItem, StockCount, StockCountLine,
                                    StockLevel, StockMovement, Transfer, TransferItem, Warehouse)
from ftapp.models.sales import Customer, CustomerPayment, Invoice, InvoiceItem
from ftapp.models.system import AICache, AuditLog, Counter, Notification, SavedReport, Setting, SyncLog

__all__ = [
    "Base", "User", "DeviceSession", "Category", "CustomField", "PriceHistory", "PriceTier", "Product",
    "ProductFieldValue", "ProductImage", "ProductTierPrice", "Promotion", "Supplier", "Currency",
    "ExchangeRateHistory", "Expense", "ExpenseCategory", "Shift", "Batch", "PurchaseInvoice",
    "PurchaseItem", "StockCount", "StockCountLine", "StockLevel", "StockMovement", "Transfer",
    "TransferItem", "Warehouse", "Customer", "CustomerPayment", "Invoice", "InvoiceItem", "AICache",
    "AuditLog", "Counter", "Notification", "SavedReport", "Setting", "SyncLog", "CashMovement",
    "CurrencyExchange", "Employee", "EmployeeTransaction",
]
