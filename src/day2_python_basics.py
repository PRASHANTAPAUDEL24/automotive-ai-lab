def calculate_achievement(sales, target):
    return sales/target*100


def get_performance_status(achievement):
    if achievement< 80:
        return "Needs attention"
    elif achievement< 100:
        return "Below target"
    else:
        return "Target achieved" 

    
dealers_data = [
    {
        "name": "Buffalo Sunset Vertex Automotive",
        "target": 32,
        "sales": 24 
    },
    {
        "name": "Columbus Westfield Vertex Auto",
        "target": 19,
        "sales": 14 
    },
    {
        "name": "Orlando Crossroads Vertex Motors",
        "target": 55,
        "sales": 22
    },
    {
        "name": "Boston Northgate Vertex Motors",
        "target": 55,
        "sales": 65
    }
]

print("\nDealer Performance:")

for dealer in dealers_data:
    achievement = calculate_achievement(
        dealer["sales"],
        dealer["target"]
    )
    
    status = get_performance_status(achievement)

    print(
        f'{dealer["name"]}: '
        f'{achievement:.1f}% - {status}'
    )