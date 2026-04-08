# yolo 결측치 처리 함수 코드
# max_consecutive_none, max_consecutive_none_middle, should_discard, fill_remaining_none


# 연속된 결측 길이 체크
def max_consecutive_none(seq):
    max_count = 0
    current = 0

    for x in seq:
        if x is None:
            current += 1
            max_count = max(max_count, current)
        else:
            current = 0

    return max_count

def max_consecutive_none_middle(seq):
    # 앞쪽부터 none이 아닌 곳을 찾음
    start = 0
    while start < len(seq) and seq[start] is None:
        start += 1

    # 뒤쪽부터 none이 아닌 곳을 찾음
    end = len(seq) - 1
    while end >= 0 and seq[end] is None:
        end -= 1
        
    # 전부 None인 경우 바로 시퀀스 길이로 반환
    if start > end:
        return len(seq)

    # 중간 부분만 검사
    trimmed = seq[start:end+1]

    return max_consecutive_none(trimmed)

# 버릴 영상인지 결정
def should_discard(seq, max_allowed_gap=5):

    # 앞, 뒤는 fill로 채워도 됨 / 중간에 있는 결측치만 체크
    max_gap = max_consecutive_none_middle(seq)

    return max_gap >= max_allowed_gap


# 남은 결측 채우기
def fill_remaining_none(seq):
    
    # 전부 None이면 처리
    if all(x is None for x in seq):
        return None

    result = seq.copy()
    
    # backward fill
    # 현재 값이 None이면 바로 뒤에 값으로 채움
    for i in range(len(result)-2, -1, -1):
        if result[i] is None:
            result[i] = result[i+1]


    # forward fill
    # 현재 값이 None이면 바로 앞 값으로 채움
    for i in range(1, len(result)):
        if result[i] is None:
            result[i] = result[i-1]

    
    return result
