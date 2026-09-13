import pandas as pd

df = pd.read_csv("ml_dataset.csv")

print(df.head())
print()
df.info()
print()
print(df["label"].value_counts())

from sklearn.model_selection import train_test_split

X = df[["std", "peak", "rms", "p2p", "zcr", "speed"]]
y = df["label"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

print(f"Train size: {len(X_train)}, Test size: {len(X_test)}")
print(y_train.value_counts())

from sklearn.tree import DecisionTreeClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

models = {
    "Decision Tree": (DecisionTreeClassifier(max_depth=5, random_state=42), X_train, X_test),
    "KNN": (KNeighborsClassifier(n_neighbors=5), X_train_scaled, X_test_scaled),
    "Random Forest": (RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42), X_train, X_test),
}

results = {}
for name, (model, xtr, xte) in models.items():
    model.fit(xtr, y_train)
    y_pred = model.predict(xte)
    acc = accuracy_score(y_test, y_pred)
    results[name] = acc
    print(f"\n=== {name} (accuracy: {acc:.3f}) ===")
    print(classification_report(y_test, y_pred))
    print("Confusion matrix (rows=true, cols=predicted):")
    labels = sorted(y.unique())
    print(pd.DataFrame(confusion_matrix(y_test, y_pred, labels=labels), index=labels, columns=labels))